#!/usr/bin/env python3
import logging
from typing import Dict, Optional, Union, List

from dataclass_utils import dataclass_from_dict
from helpermodules.cli import run_using_positional_cli_args
from modules.common.abstract_device import AbstractDevice, DeviceDescriptor
from modules.common.component_context import MultiComponentUpdateContext
from modules.common.store import get_inverter_value_store
from modules.devices.batterx import bat, external_inverter
from modules.devices.batterx import counter
from modules.devices.batterx import inverter
from modules.devices.batterx.config import BatterX, BatterXBatSetup, BatterXCounterSetup, BatterXInverterSetup
from modules.common import req

log = logging.getLogger(__name__)


batterx_component_classes = Union[bat.BatterXBat, counter.BatterXCounter,
                                  inverter.BatterXInverter]


class Device(AbstractDevice):
    COMPONENT_TYPE_TO_CLASS = {
        "bat": bat.BatterXBat,
        "counter": counter.BatterXCounter,
        "inverter": inverter.BatterXInverter,
    }

    def __init__(self, device_config: Union[Dict, BatterX]) -> None:
        self.components = {}  # type: Dict[str, batterx_component_classes]
        try:
            self.device_config = dataclass_from_dict(BatterX, device_config)
        except Exception:
            log.exception("Fehler im Modul "+self.device_config.name)

    def add_component(self, component_config: Union[Dict,
                                                    BatterXBatSetup,
                                                    BatterXCounterSetup,
                                                    BatterXInverterSetup]) -> None:
        if isinstance(component_config, Dict):
            component_type = component_config["type"]
        else:
            component_type = component_config.type
        component_config = dataclass_from_dict(COMPONENT_TYPE_TO_MODULE[
            component_type].component_descriptor.configuration_factory, component_config)
        if component_type in self.COMPONENT_TYPE_TO_CLASS:
            self.components["component"+str(component_config.id)] = (self.COMPONENT_TYPE_TO_CLASS[component_type](
                self.device_config.id, component_config))
        else:
            raise Exception(
                "illegal component type " + component_type + ". Allowed values: " +
                ','.join(self.COMPONENT_TYPE_TO_CLASS.keys())
            )

    def update(self) -> None:
        log.debug("Start device reading " + str(self.components))
        if self.components:
            with MultiComponentUpdateContext(self.components):
                resp_json = req.get_http_session().get(
                    'http://' + self.device_config.configuration.ip_address + '/api.php?get=currentstate',
                    timeout=5).json()
                for component in self.components:
                    self.components[component].update(resp_json)
        else:
            log.warning(
                self.device_config.name +
                ": Es konnten keine Werte gelesen werden, da noch keine Komponenten konfiguriert wurden."
            )


COMPONENT_TYPE_TO_MODULE = {
    "bat": bat,
    "counter": counter,
    "inverter": inverter,
    "external_inverter": external_inverter
}


def read_legacy(
        component_type: str,
        ip_address: str,
        num: Optional[int] = None,
        evu_counter: Optional[str] = None,
        bat_module: Optional[str] = None,
        ext_inverter: int = 0) -> None:

    device_config = BatterX()
    device_config.configuration.ip_address = ip_address
    dev = Device(device_config)
    dev = _add_component(dev, component_type, num)
    if evu_counter == "bezug_batterx":
        dev = _add_component(dev, "counter", 0)
    if bat_module == "speicher_batterx":
        dev = _add_component(dev, "bat", 3)

    log.debug('BatterX IP-Adresse: ' + ip_address)
    log.debug('BatterX externer WR: ' + str(ext_inverter))

    with MultiComponentUpdateContext(dev.components):
        resp_json = req.get_http_session().get(
            'http://' + ip_address + '/api.php?get=currentstate',
            timeout=5).json()
        for component in dev.components.values():
            if isinstance(component, (bat.BatterXBat, counter.BatterXCounter)):
                component.update(resp_json)
            elif isinstance(component, inverter.BatterXInverter):
                if ext_inverter == 0:
                    component.update(resp_json)
                else:
                    dev = _add_component(dev, "external_inverter", 4)
                    power = component.get_power(resp_json)
                    power_ext = dev.components["component4"].get_power(resp_json)
                    state = component.get_inverter_state(power+power_ext)
                    get_inverter_value_store(num).set(state)


def _add_component(dev: Device, component_type: str, num: Optional[int]) -> Device:
    if component_type in COMPONENT_TYPE_TO_MODULE:
        component_config = COMPONENT_TYPE_TO_MODULE[component_type].component_descriptor.configuration_factory()
    else:
        raise Exception(
            "illegal component type " + component_type + ". Allowed values: " +
            ','.join(COMPONENT_TYPE_TO_MODULE.keys())
        )
    component_config.id = num
    dev.add_component(component_config)
    return dev


def main(argv: List[str]) -> None:
    run_using_positional_cli_args(read_legacy, argv)


device_descriptor = DeviceDescriptor(configuration_factory=BatterX)
