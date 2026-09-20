"""Execute torchvision on CPU and export measured shapes/parameters/Conv+Linear MACs.

Install the pinned CPU wheels into .model_runtime (see GUI_GUIDE_zh-TW.md).
No pretrained weights or network are needed to run this script afterwards.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".model_runtime"))
import torch
import torchvision
from torch import nn
from torchvision import models

MIB = 1024 ** 2
EXPECTED = {"resnet50": 25557032, "resnet18": 11689512,
            "mobilenet_v2": 3504872, "squeezenet1_1": 1235496}
SOURCES = {
    "resnet18": "https://docs.pytorch.org/vision/0.21/_modules/torchvision/models/resnet.html",
    "resnet50": "https://docs.pytorch.org/vision/0.21/_modules/torchvision/models/resnet.html",
    "mobilenet_v2": "https://docs.pytorch.org/vision/0.21/_modules/torchvision/models/mobilenetv2.html",
    "squeezenet1_1": "https://docs.pytorch.org/vision/0.21/_modules/torchvision/models/squeezenet.html",
}


def size(tensor):
    return tensor.numel() * tensor.element_size() / MIB


def units(name, net):
    if name.startswith("resnet"):
        yield "stem", nn.Sequential(net.conv1, net.bn1, net.relu, net.maxpool), "stem"
        for stage in range(1, 5):
            for i, block in enumerate(getattr(net, f"layer{stage}")):
                yield f"layer{stage}.{i}", block, "residual"
        yield "head", nn.Sequential(net.avgpool, nn.Flatten(), net.fc), "head"
    elif name == "mobilenet_v2":
        for i, block in enumerate(net.features):
            yield f"features.{i}", block, "inverted_residual" if hasattr(block, "use_res_connect") else "conv"
        yield "head", nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), net.classifier), "head"
    else:
        fs = list(net.features)
        yield "stem", nn.Sequential(*fs[:3]), "stem"
        i = 3
        while i < len(fs):
            group, start = [fs[i]], i
            i += 1
            if i < len(fs) and isinstance(fs[i], nn.MaxPool2d):
                group.append(fs[i])
                i += 1
            yield f"fire.{start}", nn.Sequential(*group), "fire"
        yield "head", nn.Sequential(net.classifier, nn.Flatten()), "head"


def extract(name):
    torch.manual_seed(20260920)
    net = getattr(models, name)(weights=None).eval()
    inp = torch.randn(1, 3, 224, 224)
    blocks, records = [], []
    x = inp
    with torch.inference_mode():
        reference = net(inp)
        for label, module, kind in units(name, net):
            ops, leaves, handles = [], [], []

            def hook(subname):
                def capture(m, args, out):
                    if not isinstance(out, torch.Tensor):
                        raise TypeError("Expected one tensor per operator")
                    leaves.append(size(out))
                    if isinstance(m, nn.Conv2d):
                        macs = out.numel() * (m.in_channels // m.groups) * math.prod(m.kernel_size)
                        ops.append(dict(name=subname, kind="depthwise" if m.groups == m.in_channels and m.groups > 1 else "conv",
                                        macs=macs, input_shape=list(args[0].shape), output_shape=list(out.shape),
                                        output_mib=size(out), in_channels=m.in_channels, out_channels=m.out_channels))
                    elif isinstance(m, nn.Linear):
                        ops.append(dict(name=subname, kind="linear", macs=out.numel() * m.in_features,
                                        input_shape=list(args[0].shape), output_shape=list(out.shape),
                                        output_mib=size(out), in_channels=m.in_features, out_channels=m.out_features))
                return capture

            for subname, sub in module.named_modules():
                if not list(sub.children()):
                    handles.append(sub.register_forward_hook(hook(subname)))
            before = x
            x = module(x)
            for handle in handles:
                handle.remove()
            params = sum(p.numel() for p in module.parameters())
            convs = [op for op in ops if op["kind"] != "linear"]
            supported = ["single", "output_channel", "input_channel"]
            inner = []
            projection = kind == "residual" and module.downsample is not None
            if kind == "residual":
                inner = [op["output_mib"] for op in convs if not op["name"].startswith("downsample")][:-1]
            elif name == "mobilenet_v2":
                supported = ["single", "output_channel"]
                # PW expansion -> DW is shard-local. DW -> dense projection
                # needs one all-gather. There is never a DW partial reduction.
                inner = [op["output_mib"] for op in convs if op["kind"] == "depthwise"]
            if kind in ("fire", "head"):
                # Keep Fire squeeze/parallel expand/concat on one chiplet until
                # offset-aware concat channel placement is implemented.
                supported = ["single"]
            block = dict(name=label, type="head" if kind == "head" else kind,
                depends_on=[blocks[-1]["name"]] if blocks else [],
                macs_g=sum(op["macs"] for op in ops) / 1e9,
                input_mb=size(before), output_mb=size(x), weight_mb=params * 4 / MIB,
                input_shape=list(before.shape), output_shape=list(x.shape), params=params,
                operators=[op["kind"] + ":" + op["name"] for op in ops],
                branch_closed=True, internal_activation_mb=inner,
                peak_activation_mb=max(leaves, default=size(x)),
                projection_shortcut=projection,
                residual_shortcut=kind == "residual" or bool(getattr(module, "use_res_connect", False)),
                reduction_output_mb=convs[-1]["output_mib"] if convs else size(x),
                parallel_channels=math.gcd(*(op["out_channels"] for op in ops)) if ops else 1,
                input_parallel_channels=math.gcd(*(op["in_channels"] for op in ops)) if ops else 1,
                supported_mappings=supported,
                input_partition="channel" if convs and convs[0]["kind"] == "depthwise" else "replicated")
            blocks.append(block)
            records.append(dict(block=label, operators=ops))
    if not torch.equal(x, reference):
        torch.testing.assert_close(x, reference, rtol=1e-5, atol=1e-6)
    assert list(x.shape) == [1, 1000] and bool(torch.isfinite(x).all())
    total_params = sum(p.numel() for p in net.parameters())
    assert total_params == EXPECTED[name] == sum(b["params"] for b in blocks)
    entry = dict(name=name, dataset="ImageNet-1K", input_shape="1x3x224x224 FP32",
                 macs_g=sum(b["macs_g"] for b in blocks), params_m=total_params / 1e6, blocks=blocks,
                 calibration=dict(source=SOURCES[name], torch=torch.__version__, torchvision=torchvision.__version__,
                                  input_shape=[1, 3, 224, 224], dtype="float32", weights="none",
                                  macs_scope="Conv2d and Linear only; grouped Conv divides by groups",
                                  accuracy_measured=False, forward_checked=True))
    report = dict(model=name, parameters=total_params, fp32_weights_mib=total_params * 4 / MIB,
                  conv_linear_macs=sum(op["macs"] for r in records for op in r["operators"]),
                  blocks=len(blocks), output_shape=list(x.shape), output_finite=True,
                  block_forward_matches_full_model=True, max_abs_difference=float((x-reference).abs().max()),
                  calibration=entry["calibration"], operator_records=records)
    return entry, report


def main():
    torch.set_num_threads(2)
    catalog_path = ROOT / "configs/models.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    reports = []
    for name in EXPECTED:
        entry, report = extract(name)
        if name == "resnet50":
            existing = next(m for m in catalog["models"] if m["name"] == name)
            assert math.isclose(existing["macs_g"], entry["macs_g"], abs_tol=1e-9)
            existing["calibration"] = entry["calibration"]
        else:
            catalog["models"] = [m for m in catalog["models"] if m["name"] != name] + [entry]
        reports.append(report)
        print(name, report["parameters"], report["conv_linear_macs"], report["blocks"], flush=True)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "validation/model_forward_validation.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
