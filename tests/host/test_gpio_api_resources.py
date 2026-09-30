# SPDX-License-Identifier: Apache-2.0
import json
import unittest
import test_resource_ownership as resources


class GpioApiResources(unittest.TestCase):
    def make_fixture(self):
        case = resources.ResourceOwnership()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.extra('bth', '''
            gpio: gpio@40081000 {
                compatible = "bestechnic,bes2700yp-gpio"; reg = <0x40081000 0x1000>;
                gpio-controller; #gpio-cells = <2>; ngpios = <18>;
                gpio-reserved-ranges = <0 12>, <13 3>;
            };
            aliases { sw0 = &key0; sw1 = &key1; led0 = &led0; };
            buttons { status = "disabled";
                key0: key-0 { gpios = <&gpio 16 17>; };
                key1: key-1 { gpios = <&gpio 17 17>; };
            };
            leds { status = "disabled"; led0: led-0 { gpios = <&gpio 12 1>; }; };
        ''')
        with (case.release / 'bth.config').open('a') as stream:
            stream.write('CONFIG_GPIO=y\nCONFIG_GPIO_BES2700YP=y\nCONFIG_BES2700YP_GPIO_VALIDATION=2\n')
        manifest = dict(validation_profile='gpio-api-led-restart')
        layout = dict(manifest, gpio_service=dict(mode=2, capabilities=56, zephyr_api=True))
        (case.release / 'manifest.json').write_text(json.dumps(manifest))
        (case.release / 'layout.json').write_text(json.dumps(layout))
        return case

    def test_only_granted_bth_controller_and_board_pins(self):
        self.make_fixture().check()
        for old, new, code in [
            ('<0 12>, <13 3>', '<0 12>', 'gpio-service-owner'),
            ('reg = <0x40081000 0x1000>', 'reg = <0x40082000 0x1000>', 'gpio-service-owner'),
            ('ngpios = <18>', 'ngpios = <32>', 'gpio-service-owner'),
            ('<&gpio 16 17>', '<&gpio 18 17>', 'gpio-board-map'),
            ('<&gpio 12 1>', '<&gpio 12 0>', 'gpio-board-map')]:
            case = self.make_fixture()
            case.change('bth', old, new)
            case.check(code)
        case = self.make_fixture()
        case.change('bth', 'CONFIG_GPIO_BES2700YP=y', 'CONFIG_GPIO_BES2700YP=n', 'config')
        case.check('gpio-profile')
        case = self.make_fixture()
        with (case.release / 'bth.config').open('a') as stream:
            stream.write('CONFIG_GPIO_HOGS=y\n')
        case.check('gpio-init-owner')

    def test_service_and_controller_must_agree(self):
        case = self.make_fixture()
        case.change('bth', 'gpio-controller;', 'status = "disabled"; gpio-controller;')
        case.check('gpio-count')
        case = self.make_fixture()
        layout = json.loads((case.release / 'layout.json').read_text())
        for invalid in (False, 1, 'true'):
            layout['gpio_service']['zephyr_api'] = invalid
            (case.release / 'layout.json').write_text(json.dumps(layout))
            case.check('gpio-profile')

    def test_irq_profile_keeps_other_routes_and_polling_profiles_closed(self):
        def irq_fixture():
            case=self.make_fixture()
            case.change('bth','<0 12>, <13 3>','<0 16>')
            case.change('bth','gpio-controller;', 'interrupt-parent = <&nvic>; interrupts = <44 3>; gpio-controller;')
            case.change('bth','CONFIG_BES2700YP_GPIO_VALIDATION=2','CONFIG_BES2700YP_GPIO_VALIDATION=1', 'config')
            with (case.release/'bth.config').open('a') as stream:
                stream.write('CONFIG_GPIO_BES2700YP_IRQ=y\n')
            manifest=dict(validation_profile='gpio-irq-input')
            layout=dict(manifest,gpio_service=dict(mode=1,capabilities=40,zephyr_api=True),
                gpio_irq_service=dict(abi=5,capabilities=64,irq=44,priority=3,pins=0x30000,
                                      request_bytes=96,snapshot_bytes=64))
            (case.release/'manifest.json').write_text(json.dumps(manifest))
            (case.release/'layout.json').write_text(json.dumps(layout))
            return case
        irq_fixture().check()
        for old,new in [('<44 3>','<9 3>'),('<44 3>','<44 2>'),('<0 16>','<0 15>')]:
            case=irq_fixture();case.change('bth',old,new);case.check('gpio-service-owner')
        case=irq_fixture();case.change('bth','CONFIG_GPIO_BES2700YP_IRQ=y','CONFIG_GPIO_BES2700YP_IRQ=n','config')
        case.check('gpio-irq-contract')
        case=self.make_fixture();case.change('bth','gpio-controller;','interrupt-parent = <&nvic>; interrupts = <44 3>; gpio-controller;')
        case.check('gpio-service-owner')
