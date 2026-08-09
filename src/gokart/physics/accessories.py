"""Low-voltage accessory load model."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.components import DcDcConverter


@dataclass(frozen=True)
class AccessoryParams:
    base_load_w: float
    dcdc_efficiency: float
    input_min_voltage_v: float

    @classmethod
    def from_component(cls, dcdc: DcDcConverter, base_load_w: float = 50.0) -> AccessoryParams:
        return cls(
            base_load_w=base_load_w,
            dcdc_efficiency=dcdc.efficiency,
            input_min_voltage_v=dcdc.input_min_voltage_v,
        )


@dataclass(frozen=True)
class AccessoryOutputs:
    hv_power_w: float
    brown_out_risk: bool


def step_accessories(pack_voltage_v: float, params: AccessoryParams) -> AccessoryOutputs:
    if pack_voltage_v <= 0 or params.dcdc_efficiency <= 0:
        return AccessoryOutputs(hv_power_w=0.0, brown_out_risk=True)
    hv_power = params.base_load_w / params.dcdc_efficiency
    brown_out = pack_voltage_v < params.input_min_voltage_v
    return AccessoryOutputs(hv_power_w=hv_power, brown_out_risk=brown_out)
