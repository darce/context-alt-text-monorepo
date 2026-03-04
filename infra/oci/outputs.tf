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
