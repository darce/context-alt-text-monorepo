"""Admit one finite remote CLI observation; all model serving stays incumbent."""
import ast
import hashlib
import json
import run_selected_root_resume_qualification as runner

P=runner.P
N='RAW-INCUMBENT-OBSERVATION-R1'
UNIT='workbay-bakeoff-raw-incumbent-observation-20261018.scope'
assert json.loads((P/'OWNER-LIVE-PROCEDURE-UPGRADE-R4.actual-capacity-return.json').read_text())['status']=='LIVE_STAGE_UPGRADED_ONLY'
source=(P/'raw_incumbent_observation.remote.py').read_bytes();ast.parse(source)
receipt=dict(source_head='ab94e904ca25e2e031ad241f2600aa0406201c15',stage='/root/owner-stop-contract-r3/procedure',
             gate='OWNER-ROOT-FIXTURE-G3',manifest_sha256='991aa72e923562bec93659190e87f9d223514da3073b424df5d36a60f1e77406',
             unit=UNIT,remote_orchestration_sha256=hashlib.sha256(source).hexdigest(),scope='borrowed_shared_runtime_technical_regression_observation',limit=1,
             no_new_server_or_weights=True,private_client_uid=1002,no_quality_or_winner_claim=True)
runner.N=N;runner.UNIT=UNIT;runner.ROLE='single_authenticated_shared_runtime_technical_observation'
def inputs(head,gate):
    runner.cap.persist(P/(N+'.prepared-inputs.json'),receipt)
    return {},receipt
runner.inputs=inputs
runner.bootstrap=lambda files,receipt:source.decode()
runner.run(receipt['source_head'],receipt['gate'])
