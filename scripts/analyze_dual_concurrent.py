#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""V08b concurrent v3 + T2 startup profile + package-duration heartbeat validator."""
import argparse,json,re
import analyze_dual_boot as heartbeat
import analyze_boot_profile as profile
from pathlib import Path
FIELDS=set('magic version pair session build phase req ack acked handled overlap error rx requests kicks done queued spurious stack max_wait pauses burst seed guard'.split())
ROW=re.compile(r'(\d+)/([IE])/BTH/IPC/MAIN \| zephyr_cc (begin|endpoint|result) (.+) !')

class Concurrent:
 @staticmethod
 def analyze(text,m):
  lines=text.splitlines();base=[];rows=[];errors=[]
  for i,line in enumerate(lines):
   if 'zephyr_cc ' not in line:base.append(line);continue
   match=ROW.fullmatch(line)
   if not match:errors.append('malformed concurrent record');continue
   ts,level,kind,body=match.groups()
   try:
    pairs=[x.split('=',1) for x in body.split()];d={k:int(v,0) for k,v in pairs}
    if len(d)!=len(pairs) or any(v<0 or v>0xffffffff for v in d.values()):raise ValueError()
   except ValueError:errors.append('bad concurrent fields');continue
   rows.append(dict(index=i,time=int(ts),level=level,kind=kind,fields=d))
  r=heartbeat.analyze('\n'.join(base)+'\n',m)
  if not r['sessions']:return r
  s=r['sessions'][0];missing=[]
  if m.get('concurrent_version')!=3:errors.append('concurrent manifest version')
  kinds=[x['kind'] for x in rows];expected=['begin','endpoint','endpoint','result']
  if kinds!=expected[:len(kinds)]:errors.append('concurrent order/duplicates')
  if len(rows)<4:missing.append('concurrent result/endpoints')
  n=m['concurrent_rounds'];pair=m['concurrent_pair']
  if rows:
   b=rows[0]
   if b['fields']!=dict(version=3,channel=1,rounds=n,pair=pair,seed=0x27003301):errors.append('concurrent begin identity')
   stages=[i for i,l in enumerate(lines) if 'zephyr_dual stage id=7 rc=0' in l]
   samples=[i for i,l in enumerate(lines) if 'zephyr_dual sample id=0 ' in l]
   if not stages or (samples and not stages[-1]<b['index']<samples[0]):errors.append('concurrent begin position')
  if any(x['level']!='I' for x in rows):errors.append('concurrent error severity')
  endpoints=[x['fields'] for x in rows if x['kind']=='endpoint']
  for side,d in enumerate(endpoints):
   if set(d)!=FIELDS|{'side'}:errors.append('concurrent endpoint fields');continue
   fixed=dict(side=side,magic=0x33434342,version=3,pair=pair,build=int(m['build' if side==0 else 'm55_build'],0),
    phase=5,req=n,ack=n,acked=n,handled=n,error=0,spurious=0,pauses=1,burst=32,seed=0x27003301,guard=0xcc335aa5)
   if any(d.get(k)!=v for k,v in fixed.items()):errors.append('concurrent endpoint result')
   if not 0<d['overlap']<=n or d['stack']<128 or d['max_wait']>2000 or not d['session']:errors.append('concurrent overlap/stack/deadline/session')
   if not 31<=d['queued']<=d['requests'] or not 0<d['kicks']==d['done']<=d['requests']<=3*n+100:errors.append('concurrent TX accounting')
  if len(endpoints)==2 and all(set(d)==FIELDS|{'side'} for d in endpoints):
   a,b=endpoints
   if a['session']!=b['session'] or a['rx']!=b['kicks'] or b['rx']!=a['kicks']:errors.append('concurrent cross-core accounting')
  if len(rows)==4:
   result=rows[-1]
   if not endpoints or result['fields']!=dict(finished=1,rc=0,session=endpoints[0].get('session')):errors.append('concurrent final result')
   if result['time']-rows[0]['time']>120000:errors.append('concurrent deadline')
   if any('zephyr_dual result ' in l for l in lines[:result['index']]):errors.append('late concurrent result')
  if any('zephyr_dual result pass=1' in l for l in lines) and missing:errors.append('heartbeat success without concurrent success')
  s['errors']+=errors;s['missing']+=missing;s['concurrent_records']=rows
  s['status']='fail' if s['errors'] else 'incomplete' if s['missing'] else 'pass'
  r['status']=s['status'];return r

def analyze(text,m):
 old=profile.dual
 try:
  profile.dual=Concurrent
  return profile.analyze(text,m)
 finally:profile.dual=old

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('log',type=Path);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--output',type=Path)
 a=ap.parse_args();r=analyze(a.log.read_bytes().decode('latin1'),json.loads(a.manifest.read_text()))
 text=json.dumps(r,indent=2)+'\n'
 if a.output:a.output.write_text(text)
 print(text,end='');return {'pass':0,'fail':1,'incomplete':2}[r['status']]
if __name__=='__main__':raise SystemExit(main())
