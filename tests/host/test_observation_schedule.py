# SPDX-License-Identifier: Apache-2.0
"""Exercise the firmware's window scheduler at completion/deadline boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ObservationSchedule(unittest.TestCase):
    def test_no_early_window_even_when_function_finishes_after_long_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'schedule.c'
            source.write_text('''#include <assert.h>
#include <bes2700_observation.h>
int main(void) {
 struct bes_observation o={0};
 assert(bes_observation_due(&o,600000)==0);
 o.functional=true;o.functional_ms=590123;
 assert(bes_observation_due(&o,600000)==0);
 assert(bes_observation_due(&o,650122)==0);
 assert(bes_observation_due(&o,650123)==1);
 o.short_done=true;
 assert(bes_observation_due(&o,650123)==2);
 o=(struct bes_observation){.functional=true,.functional_ms=7001};
 assert(bes_observation_due(&o,67000)==0);
 assert(bes_observation_due(&o,67001)==1);
 o.short_done=true;
 assert(bes_observation_due(&o,599999)==0);
 assert(bes_observation_due(&o,600000)==2);
 assert(bes_observation_due(&o,7000)==0);
 return 0;
}
''')
            binary=root/'schedule'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                            '-I'+str(ROOT/'include/bestechnic/bes2700yp'),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
