"""Tensor ownership -> unicast flows, shared by Rapid, E2E and scheduling.

Intervals describe contiguous channel shards of one tensor. Broadcast is a
separate unicast copy per consumer (no assumed hardware multicast). IC outputs
are full partial tensors, reduced to the group's first chiplet before reuse.
"""
from __future__ import annotations
import math

BITS_PER_MIB = 8 * 1024**2


def ownership(ids, strategy, *, output):
    if not ids or strategy not in ("single", "output_channel", "input_channel"):
        raise ValueError("tensor ownership requires chiplets and a supported mapping strategy")
    if strategy == "single" or (output and strategy == "input_channel"):
        return ((ids[0], 0.0, 1.0),)
    if not output and strategy == "output_channel":
        return tuple((node, 0.0, 1.0) for node in ids)
    return tuple((node, i / len(ids), (i + 1) / len(ids)) for i, node in enumerate(ids))


def redistribute(sources, destinations, mib):
    """Each destination receives exactly its requested interval, including local data."""
    if not math.isfinite(mib) or mib < 0:
        raise ValueError("tensor MiB must be finite and nonnegative")
    for node, left, right in (*sources, *destinations):
        if not (0 <= left < right <= 1):
            raise ValueError("tensor ownership intervals must lie within [0,1]")
    ordered_sources = sorted(sources, key=lambda part: part[1])
    if any(a[2] > b[1] + 1e-9 for a, b in zip(ordered_sources, ordered_sources[1:])):
        raise ValueError("source ownership intervals must not overlap")
    flows = []
    for dst, left, right in destinations:
        received = 0.0
        for src, start, end in sources:
            overlap = max(0.0, min(end, right) - max(start, left))
            received += overlap
            if overlap > 0 and src != dst and mib > 0:
                flows.append({"source": src, "target": dst,
                              "bits": mib * BITS_PER_MIB * overlap})
        if abs(received - (right - left)) > 1e-9:
            raise ValueError("source ownership must cover each requested tensor shard exactly once")
    return flows


def build_communication_events(model, groups, strategies):
    group_ids, owner = [], {}
    cursor = 0
    for gi, (start, end, parts) in enumerate(groups):
        group_ids.append(tuple(range(cursor, cursor + parts)))
        cursor += parts
        for bi in range(start, end):
            owner[bi] = gi
    index = {b.name: i for i, b in enumerate(model.blocks)}
    events = []

    def add(kind, source_block, dest_block, sg, dg, mib, flows, tensor):
        if flows:
            events.append(dict(event_id=len(events), kind=kind, tensor=tensor,
                source_block=source_block, destination_block=dest_block,
                source_group_index=sg, destination_group_index=dg,
                tensor_mib=mib, traffic_bits=sum(f["bits"] for f in flows), flows=flows))

    def reduce_output(b, gi, ids, mib, label):
        add("partial_output_reduction", b.name, b.name, gi, gi, mib,
            [dict(source=node, target=ids[0], bits=mib * BITS_PER_MIB) for node in ids[1:]], label)

    for bi, block in enumerate(model.blocks):
        gi = owner[bi]
        ids, strategy = group_ids[gi], strategies[gi]
        wanted = ownership(ids, strategy, output=False)
        if strategy == "output_channel" and block.input_partition == "channel":
            # A leading depthwise operator consumes corresponding input shards;
            # it does not need dense-Conv broadcast or partial-sum reduction.
            wanted = ownership(ids, strategy, output=True)
        # Keep a full input already resident on this group's reduction leader.
        # This includes external input and a preceding same-group IC result.
        leader_has_full_input = not block.depends_on
        if not block.depends_on:
            add("input_distribution", "external", block.name, gi, gi, block.input_mb,
                redistribute(((ids[0], 0., 1.),), wanted, block.input_mb), block.name + ":input")
        for dep in block.depends_on:
            pi = index[dep]
            pg = owner[pi]
            prev = model.blocks[pi]
            source_owners = ownership(group_ids[pg], strategies[pg], output=True)
            if len(block.depends_on) == 1:
                leader_has_full_input = (ids[0], 0., 1.) in source_owners
            # Every dependency has its own tensor identity, including fan-out/join.
            add("dependency_transfer", dep, block.name, pg, gi, prev.output_mb,
                redistribute(source_owners, wanted, prev.output_mb), dep + ":output")
        if len(ids) == 1:
            continue
        # Optional inner Conv activation boundaries; calibrated ResNet supplies
        # these so grouping/fusion never silently erases required redistributions.
        for j, mib in enumerate(block.internal_activation_mb):
            if strategy == "input_channel":
                reduce_output(block, gi, ids, mib, f"{block.name}:inner{j}:partial")
            add("internal_redistribution", block.name, block.name, gi, gi, mib,
                redistribute(ownership(ids, strategy, output=True),
                             ownership(ids, strategy, output=False), mib),
                f"{block.name}:inner{j}")
        if strategy == "input_channel":
            reduce_output(block, gi, ids, block.reduction_output_mb or block.output_mb, block.name + ":output:partial")
            if block.projection_shortcut:
                reduce_output(block, gi, ids, block.output_mb, block.name + ":shortcut:partial")
            elif block.residual_shortcut and not leader_has_full_input:
                add("identity_shortcut_gather", block.name, block.name, gi, gi, block.input_mb,
                    redistribute(ownership(ids, strategy, output=False), ((ids[0], 0., 1.),), block.input_mb),
                    block.name + ":identity")
    return tuple(events)


def aggregate_flows(events):
    traffic = {}
    for event in events:
        for flow in event["flows"]:
            pair = (flow["source"], flow["target"])
            traffic[pair] = traffic.get(pair, 0.0) + flow["bits"]
    return traffic
