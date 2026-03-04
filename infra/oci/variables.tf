variable "tenancy_ocid" {
  description = "OCI tenancy OCID"
  type        = string
}

variable "user_ocid" {
  description = "OCI user OCID"
  type        = string
}

variable "fingerprint" {
  description = "Fingerprint for OCI API signing key"
  type        = string
}

variable "private_key_path" {
  description = "Path to OCI API private key"
  type        = string
}

variable "region" {
  description = "OCI region"
  type        = string
}

variable "compartment_ocid" {
  description = "OCI compartment OCID"
  type        = string
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for instance access"
  type        = string
}

variable "availability_domain" {
  description = "OCI availability domain (e.g. saEG:US-ASHBURN-AD-1)"
  type        = string
}

variable "ubuntu_image_ocid" {
  description = "OCID of the Ubuntu ARM image"
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed to SSH into the instance"
  type        = list(string)
  default     = [] # H-OCI-6: Default to empty to force user configuration

  validation {
    condition     = length(var.ssh_allowed_cidrs) > 0
    error_message = "Set ssh_allowed_cidrs in terraform.tfvars (e.g. ssh_allowed_cidrs = [\"YOUR_IP/32\"]). Never use 0.0.0.0/0."
  }
}

