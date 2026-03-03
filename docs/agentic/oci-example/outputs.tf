# Terraform Outputs for OCI Deployment

output "instance_id" {
  description = "OCID of the compute instance"
  value       = oci_core_instance.marketing_backend.id
}

output "instance_public_ip" {
  description = "Public IP address of the compute instance"
  value       = oci_core_instance.marketing_backend.public_ip
}

output "instance_private_ip" {
  description = "Private IP address of the compute instance"
  value       = oci_core_instance.marketing_backend.private_ip
}

output "vcn_id" {
  description = "OCID of the VCN"
  value       = oci_core_vcn.marketing_vcn.id
}

output "subnet_id" {
  description = "OCID of the public subnet"
  value       = oci_core_subnet.marketing_subnet.id
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh ubuntu@${oci_core_instance.marketing_backend.public_ip}"
}

output "backend_url" {
  description = "Backend service URL"
  value       = "http://${oci_core_instance.marketing_backend.public_ip}:3000"
}
