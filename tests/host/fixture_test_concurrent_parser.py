# SPDX-License-Identifier: Apache-2.0
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from fixture_test_boot_profile import fixture as profile_fixture,manifest as profile_manifest
from analyze_dual_concurrent import analyze,FIELDS
def manifest():
 return dict(profile_manifest(),profile_variant=2,concurrent_version=3,concurrent_rounds=10000,concurrent_pair=0x12344321)
def fixture():
 lines=profile_fixture().replace('version=1 variant=0','version=1 variant=2').splitlines();out=[]
 def row(kind,d):return '1100/I/BTH/IPC/MAIN | zephyr_cc '+kind+' '+' '.join(f'{k}={v}' for k,v in d.items())+' !'
 for line in lines:
  if 'zephyr_db begin' in line:
   out.append('0/I/BTH/IPC/MAIN | zephyr_cc begin version=3 channel=1 rounds=10000 pair=305414945 seed=654324481 !')
  elif 'zephyr_db result' in line:
   for side in (0,1):
    d={k:0 for k in sorted(FIELDS)}
    d.update(side=side,magic=0x33434342,version=3,pair=0x12344321,session=100,build=int(manifest()['build' if side==0 else 'm55_build'],0),phase=5,req=10000,ack=10000,acked=10000,handled=10000,overlap=5000,rx=10005,requests=10036,kicks=10005,done=10005,queued=31,stack=2000,max_wait=201,pauses=1,burst=32,seed=0x27003301,guard=0xcc335aa5)
    out.append(row('endpoint',d))
   out.append(row('result',dict(finished=1,rc=0,session=100)))
  else:out.append(line)
 return '\n'.join(out)+'\n'
class ConcurrentParser(unittest.TestCase):
 def test_success_missing_and_old_rejected(self):
  self.assertEqual(analyze(fixture(),manifest())['status'],'pass')
  self.assertEqual(analyze(profile_fixture(),manifest())['status'],'fail')
  self.assertEqual(analyze(fixture().split('2100/I/BTH/KERN/MAIN')[0],manifest())['status'],'incomplete')
  self.assertEqual(analyze(fixture()+fixture().split('1100/I/BTH/IPC/MAIN')[0],manifest())['status'],'incomplete')
 def test_corruption(self):
  for a,b in [('overlap=5000','overlap=0'),('req=10000','req=9999'),('acked=10000','acked=9999'),('phase=5','phase=4'),('queued=31','queued=0'),('pauses=1','pauses=0'),('side=1','side=0'),('spurious=0','spurious=1'),('error=0','error=3'),('stack=2000','stack=64'),('session=100','session=0'),('burst=32','burst=0'),('max_wait=201','max_wait=3000'),('rx=10005','rx=10006')]:
   with self.subTest(a=a):self.assertEqual(analyze(fixture().replace(a,b,1),manifest())['status'],'fail')
 def test_missing_duplicate_reorder(self):
  lines=fixture().splitlines()
  for i,line in enumerate(lines):
   if 'zephyr_cc ' in line:
    for altered in [lines[:i]+lines[i+1:],lines[:i]+[line]+lines[i:]]:
     self.assertEqual(analyze('\n'.join(altered)+'\n',manifest())['status'],'fail')
 def test_cli(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'layout.json').write_text(json.dumps(manifest()))
   for text,code in [(fixture(),0),(fixture().replace('overlap=5000','overlap=0'),1),(fixture().split('2100/I/BTH/KERN/MAIN')[0],2)]:
    (p/'log').write_text(text)
    r=subprocess.run([sys.executable,str(Path(__file__).with_name('analyze_dual_concurrent.py')),str(p/'log'),'--manifest',str(p/'layout.json')],capture_output=True,text=True)
    self.assertEqual(r.returncode,code,r.stderr)
