variable "tenancy_ocid" {
  description = "OCID of the OCI tenancy"
  type        = string
}

variable "user_ocid" {
  description = "OCID of the OCI user"
  type        = string
}

variable "fingerprint" {
  description = "Fingerprint of the OCI API key"
  type        = string
}

variable "private_key_path" {
  description = "Path to OCI API private key"
  type        = string
  default     = "~/.oci/oci_api_key.pem"
}

variable "region" {
  description = "OCI region (home region recommended for Always Free)"
  type        = string
  default     = "us-ashburn-1"
}

variable "compartment_ocid" {
  description = "OCID of the OCI compartment"
  type        = string
}

variable "availability_domain" {
  description = "Availability domain, e.g. saEG:US-ASHBURN-AD-1"
  type        = string
}

variable "ubuntu_image_ocid" {
  description = "Ubuntu image OCID for the selected region/shape"
  type        = string
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key used for instance access"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_allowed_cidrs" {
  description = "CIDR allowlist for SSH ingress"
  type        = list(string)
}

variable "enable_app_port" {
  description = "Whether to expose app_port ingress for temporary debug"
  type        = bool
  default     = false
}

variable "app_port" {
  description = "Optional debug app port"
  type        = number
  default     = 8000

  validation {
    condition     = var.app_port >= 1 && var.app_port <= 65535
    error_message = "app_port must be between 1 and 65535."
  }
}

variable "app_allowed_cidrs" {
  description = "CIDR allowlist for optional app_port ingress"
  type        = list(string)
  default     = []
}

variable "shape" {
  description = "OCI compute shape"
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "ocpus" {
  description = "Number of OCPUs"
  type        = number
  default     = 4
}

variable "memory_in_gbs" {
  description = "Memory in GB"
  type        = number
  default     = 24
}

variable "boot_volume_size_in_gbs" {
  description = "Boot volume size in GB"
  type        = number
  default     = 200
}

variable "freeform_tags" {
  description = "Freeform tags applied to the instance"
  type        = map(string)
  default = {
    project    = "acx"
    managed_by = "terraform"
    env        = "production"
  }
}
