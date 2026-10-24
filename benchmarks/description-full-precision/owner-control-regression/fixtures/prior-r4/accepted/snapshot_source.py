import hashlib,json

def check(condition,message):
 if not condition: raise RuntimeError(message)

def project_authority(raw,floor):
 """The only authority shape any guard sees; bounded by construction (RES-05).

 floor=None selects the newest record only (highest_sequence). Records below
 the floor are fenced by the native authority (STOR-10) and decide nothing, so
 they are counted and hashed but never transferred. sha256 covers the exact
 persisted bytes that were read, so equal digests mean unchanged authority.
 """
 a=json.loads(raw); check(type(a) is dict and type(a.get('intents')) is dict,'unknown authority')
 high=a['highest_sequence']; check(type(high) is int and high>=0,'unknown authority')
 if floor is None: floor=high
 check(type(floor) is int and floor>=0,'unknown authority floor')
 intents={}
 for nonce,record in a['intents'].items():
  check(type(record) is dict and type(record.get('sequence')) is int,'unknown authority record')
  if record['sequence']>=floor: intents[nonce]=record
 return dict(highest_sequence=high,rejected_sequences=a.get('rejected_sequences'),intent_count=len(a['intents']),
             sha256=hashlib.sha256(raw).hexdigest(),intents=intents)
