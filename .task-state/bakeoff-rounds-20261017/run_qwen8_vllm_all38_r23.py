"""Admit one finite remote CLI observation; all model serving stays incumbent."""
import ast
import hashlib
import json
import run_selected_root_resume_qualification as runner

P=runner.P
N='QWEN8-VLLM-ALL38-R23'
UNIT='workbay-bakeoff-qwen8-vllm-all38-r23-20261019.scope'
assert json.loads((P/'MINICPM46-ALL-IMAGES-R12.actual-capacity-return.json').read_text())['remaining_actor_claim']==0
assert json.loads((P/'WINDOW-CHECKPOINT-LIVE-R2.actual-capacity-return.json').read_text())['remaining_actor_claim']==0
assert json.loads((P/'WINDOW-CHECKPOINT-LIVE-R2-AUDIT1.actual-capacity-return.json').read_text())['remaining_actor_claim']==0
source=(P/'QWEN8-VLLM-ALL38-R23.remote.py').read_bytes();ast.parse(source)
receipt=dict(source_head='01f752a703310f80ce3b454e1d947da155d1cb6f',stage='/root/bakeoff-owner-long-window-20261019-45c86daf3bc3/procedure',
             gate='BAKEOFF-LONG-WINDOW-G1',manifest_sha256='45c86daf3bc312eea23ab1382965b56dcbc1c97dd1c82070decc6ee617d3c5ca',
             unit=UNIT,remote_orchestration_sha256=hashlib.sha256(source).hexdigest(),scope='authorized_single_GPU_maintenance_restore_Qwen',limit=38,
             no_new_weights=True, temporary_owned_candidate=True, restore_original_Qwen=True,private_client_uid=1002,no_quality_or_winner_claim=True)
receipt.update(guest_bootstrap_CPU=2,guest_bootstrap_RAM=40*1024**3,guest_bootstrap_RuntimeMaxSec=540,guest_bootstrap_transport_timeout=570,intent_seconds=1800,whole_client_seconds=1200,candidate_runtime_seconds=1500,guest_candidate_CPU=8,guest_candidate_RAM=64*1024**3,guest_controller_CPU=.25,guest_controller_RAM=256*1024**2,guest_parallel_asset_CPU=0,guest_parallel_asset_RAM=0,guest_parallel_asset_forward_bytes=0,guest_asset_fixed_max_seconds=0,guest_asset_workers=0,no_additional_GPU=True,sibling_deployments_held=True)
receipt.update(runtime_profile=dict(runtime='vLLM v0.11 BF16',context=8192,image_max_pixels=1572864,renderer_equal_to_llama=False),reviewed_helper_sha256=next(ast.literal_eval(n.value)for n in ast.parse(source).body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='HELPER_SHA256'for t in n.targets)))
assert len(receipt['reviewed_helper_sha256'])==64 and all(c in '0123456789abcdef'for c in receipt['reviewed_helper_sha256']),'Unfilled reviewed helper pin'
runner.N=N;runner.UNIT=UNIT;runner.ROLE='single_GPU_QWEN8-VLLM-ALL38-R23_one_residency_restore_Qwen'
def inputs(head,gate):
    assert json.loads((P/'BAKEOFF-LONG-WINDOW-G1.custody.json').read_bytes())['manifest']['report']['status']=='PASS'
    assert json.loads((P/'BAKEOFF-LONG-WINDOW-NATIVE-R1.custody.json').read_bytes())['manifest']['terminal']['source']==head
    assert (P/'BAKEOFF-LONG-WINDOW-NATIVE-R1.actual-capacity-return.json').exists()
    runner.cap.persist(P/(N+'.prepared-inputs.json'),receipt)
    return {},receipt
runner.inputs=inputs
runner.bootstrap=lambda files,receipt:source.decode()
runner.run(receipt['source_head'],receipt['gate'])
