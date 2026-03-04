output "instance_id" {
  description = "OCID of the compute instance"
  value       = oci_core_instance.acx_backend.id
}

output "public_ip" {
  description = "Primary public IP address"
  value       = data.oci_core_vnic.acx_backend_primary_vnic.public_ip_address
}

output "private_ip" {
  description = "Primary private IP address"
  value       = data.oci_core_vnic.acx_backend_primary_vnic.private_ip_address
}

output "vcn_id" {
  description = "OCID of the VCN"
  value       = oci_core_vcn.acx_vcn.id
}

output "subnet_id" {
  description = "OCID of the public subnet"
  value       = oci_core_subnet.acx_public_subnet.id
}

output "ssh_command" {
  description = "SSH command for instance access"
  value       = "ssh ubuntu@${data.oci_core_vnic.acx_backend_primary_vnic.public_ip_address}"
}

output "backend_url" {
  description = "Public HTTPS endpoint routed by reverse proxy"
  value       = "https://${data.oci_core_vnic.acx_backend_primary_vnic.public_ip_address}"
}

output "debug_backend_url" {
  description = "Optional direct app-port URL (null when disabled)"
  value       = var.enable_app_port ? "http://${data.oci_core_vnic.acx_backend_primary_vnic.public_ip_address}:${var.app_port}" : null
}
