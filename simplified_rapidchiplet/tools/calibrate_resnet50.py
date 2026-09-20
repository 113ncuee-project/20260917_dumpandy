"""Deterministic ResNet-50 v1.5 metadata, N=1, FP32, 1000 classes.

Source: https://docs.pytorch.org/vision/0.18/_modules/torchvision/models/resnet.html
Counts Conv/Linear MACs and trainable parameters (including BN affine, no buffers).
This is formula-derived metadata, not a measured execution or accuracy benchmark.
"""
import json
from pathlib import Path


def build_resnet50():
    mib = lambda n: n * 4 / 1024**2
    blocks = [dict(name="stem", type="Stem", source_stage="conv1", macs_g=112**2 * 3 * 64 * 49 / 1e9,
        parameter_count=3 * 64 * 49 + 128, input_mb=mib(3 * 224**2), output_mb=mib(64 * 56**2),
        reduction_output_mb=mib(64 * 112**2), input_shape=[3,224,224], output_shape=[64,56,56],
        parallel_channels=64, input_parallel_channels=3, internal_activation_mb=[],
        operators=["7x7 Conv+BN+ReLU", "MaxPool"], branch_closed=True, depends_on=[])]
    cin, hin = 64, 56
    for stage, (planes, count) in enumerate(((64,3),(128,4),(256,6),(512,3)), 2):
        for block in range(1, count+1):
            stride = 2 if stage > 2 and block == 1 else 1
            hout, cout = hin // stride, planes * 4
            projection = stride != 1 or cin != cout
            params = cin*planes + 9*planes**2 + planes*cout + 4*planes + 2*cout
            macs = hin**2*cin*planes + hout**2*(9*planes**2 + planes*cout)
            if projection:
                params += cin*cout + 2*cout
                macs += hout**2*cin*cout
            blocks.append(dict(name=f"conv{stage}_x.b{block}", type="Bottleneck", source_stage=f"conv{stage}_x",
                macs_g=macs/1e9, parameter_count=params, input_mb=mib(cin*hin**2), output_mb=mib(cout*hout**2),
                input_shape=[cin,hin,hin], output_shape=[cout,hout,hout], parallel_channels=planes,
                input_parallel_channels=min(cin,planes), internal_activation_mb=[mib(planes*hin**2),mib(planes*hout**2)],
                projection_shortcut=projection, residual_shortcut=True,
                operators=["1x1 Conv+BN+ReLU","3x3 Conv+BN+ReLU","1x1 Conv+BN",
                           "Projection Shortcut+Add+ReLU" if projection else "Identity Shortcut+Add+ReLU"],
                branch_closed=True, depends_on=[blocks[-1]["name"]]))
            cin, hin = cout, hout
    blocks.append(dict(name="head", type="Head", source_stage="head", macs_g=2048*1000/1e9,
        parameter_count=2048*1000+1000, input_mb=mib(2048*7**2), output_mb=mib(1000),
        input_shape=[2048,7,7], output_shape=[1000], operators=["GlobalAvgPool","FullyConnected"],
        branch_closed=True, depends_on=[blocks[-1]["name"]]))
    for b in blocks:
        b["weight_mb"] = mib(b["parameter_count"])
    assert sum(b["parameter_count"] for b in blocks) == 25557032
    return dict(name="resnet50", macs_g=sum(b["macs_g"] for b in blocks), params_m=25.557032,
        metadata=dict(variant="torchvision_resnet50_v1.5", batch_size=1, dtype="float32", size_unit="MiB",
            provenance="formula_derived_from_torchvision_0.18", mac_scope="Conv2d_and_Linear_only",
            reference="https://docs.pytorch.org/vision/0.18/_modules/torchvision/models/resnet.html"), blocks=blocks)


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "configs/models.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["models"] = [build_resnet50() if m["name"] == "resnet50" else m for m in data["models"]]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
