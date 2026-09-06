output "instance_id" {
  value = oci_core_instance.acx_backend.id
}

output "public_ip" {
  value = oci_core_instance.acx_backend.public_ip
}

output "ssh_command" {
  value = "ssh ubuntu@${oci_core_instance.acx_backend.public_ip}"
}

output "backend_url" {
  value = "https://${oci_core_instance.acx_backend.public_ip}"
}

output "private_ip" {
  value = oci_core_instance.acx_backend.private_ip
}

output "vcn_id" {
  value = oci_core_vcn.acx_vcn.id
}

# GPU burst host — feed ACX_GPU_ENDPOINT_URL on the description service.
# Allowlist accepts private IP literals (see deps._is_private_gpu_endpoint).
output "gpu_instance_id" {
  description = "OCID of the acx_gpu_burst instance (for idle-reaper STOP/START)."
  value       = oci_core_instance.acx_gpu_burst.id
}

output "gpu_private_ip" {
  description = "Private IP of the GPU VLM host (VCN-internal only)."
  value       = oci_core_instance.acx_gpu_burst.private_ip
}

output "gpu_endpoint_url" {
  description = "Infra-produced value for ACX_GPU_ENDPOINT_URL (http://<private-ip>:8000)."
  value       = "http://${oci_core_instance.acx_gpu_burst.private_ip}:8000"
}

output "self_stop_dynamic_group_id" {
  description = "OCID of the dynamic group used by the GPU instance self-stop watchdog."
  value       = oci_identity_dynamic_group.acx_gpu_self_stop.id
}

output "gpu_max_uptime_seconds" {
  description = "Configured maximum GPU instance uptime in seconds before self-stop."
  value       = var.gpu_max_uptime_seconds
}
