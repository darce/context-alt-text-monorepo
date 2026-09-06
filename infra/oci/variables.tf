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

variable "gpu_image_ocid" {
  description = "OCID of the x86_64 GPU golden image with NVIDIA drivers, Docker, nvidia-container-toolkit, and measurement weights baked"
  type        = string
}

variable "gpu_shape" {
  description = "OCI GPU shape for the bursty detailed-description tier"
  type        = string
  default     = "VM.GPU.A10.1"
}

variable "gpu_boot_volume_size_in_gbs" {
  description = "Boot volume size for the GPU burst instance and baked VLM weights"
  type        = number
  default     = 400
}

variable "gpu_max_uptime_seconds" {
  description = "Maximum uptime before the GPU host's independent on-instance self-stop timer runs"
  type        = number
  default     = 3600

  validation {
    condition     = var.gpu_max_uptime_seconds >= 1 && var.gpu_max_uptime_seconds == floor(var.gpu_max_uptime_seconds)
    error_message = "gpu_max_uptime_seconds must be a positive whole number of seconds."
  }
}

variable "gpu_self_stop_enabled" {
  description = "Enable the GPU host's independent on-instance maximum-uptime self-stop watchdog"
  type        = bool
  default     = true
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
