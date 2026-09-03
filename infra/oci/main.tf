terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 7.0"
    }
  }
}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = pathexpand(var.private_key_path)
  region           = var.region
}

# --- Networking ---

resource "oci_core_vcn" "acx_vcn" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "acx-vcn"
  dns_label      = "acxvcn"
}

resource "oci_core_internet_gateway" "acx_ig" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-internet-gateway"
}

# NAT gateway: private GPU hosts need outbound egress (model/image pulls,
# OS updates, NTP, Instance Principal) without a public IP.
resource "oci_core_nat_gateway" "acx_nat" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-nat-gateway"
}

resource "oci_core_route_table" "acx_rt" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-route-table"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.acx_ig.id
  }
}

# Private subnet route table: default route via NAT (not IGW).
resource "oci_core_route_table" "acx_private_rt" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-private-route-table"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.acx_nat.id
  }
}

# Public-backend security list: operator SSH allowlist + world HTTP/HTTPS.
# Does NOT open SSH from the whole VCN (VLMFIX-S2-06) — that would let a
# compromised VCN host attempt SSH to acx-backend.
resource "oci_core_security_list" "acx_security_list" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-security-list"

  # SSH (restricted CIDR allowlist only)
  dynamic "ingress_security_rules" {
    for_each = var.ssh_allowed_cidrs
    content {
      description = "SSH from ${ingress_security_rules.value}"
      protocol    = "6"
      source      = ingress_security_rules.value
      stateless   = false
      tcp_options {
        min = 22
        max = 22
      }
    }
  }

  # HTTP (Let's Encrypt ACME challenge + redirect to HTTPS)
  ingress_security_rules {
    description = "HTTP"
    protocol    = "6"
    source      = "0.0.0.0/0"
    stateless   = false
    tcp_options {
      min = 80
      max = 80
    }
  }

  # HTTPS
  ingress_security_rules {
    description = "HTTPS"
    protocol    = "6"
    source      = "0.0.0.0/0"
    stateless   = false
    tcp_options {
      min = 443
      max = 443
    }
  }

  # Egress
  egress_security_rules {
    description = "Allow all outbound"
    protocol    = "all"
    destination = "0.0.0.0/0"
    stateless   = false
  }
}

# Private GPU subnet security list: no world-open 80/443 inheritance.
# SSH from operator CIDRs + backend subnet only; VLM :8000 from VCN.
resource "oci_core_security_list" "acx_gpu_security_list" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-gpu-security-list"

  dynamic "ingress_security_rules" {
    for_each = var.ssh_allowed_cidrs
    content {
      description = "SSH from ${ingress_security_rules.value}"
      protocol    = "6"
      source      = ingress_security_rules.value
      stateless   = false
      tcp_options {
        min = 22
        max = 22
      }
    }
  }

  # Jump-host path: acx-backend (public subnet 10.0.1.0/24) → GPU.
  ingress_security_rules {
    description = "SSH from acx-backend subnet"
    protocol    = "6"
    source      = "10.0.1.0/24"
    stateless   = false
    tcp_options {
      min = 22
      max = 22
    }
  }

  ingress_security_rules {
    description = "GPU VLM endpoint from ACX VCN"
    protocol    = "6"
    source      = "10.0.0.0/16"
    stateless   = false
    tcp_options {
      min = 8000
      max = 8000
    }
  }

  egress_security_rules {
    description = "Allow all outbound"
    protocol    = "all"
    destination = "0.0.0.0/0"
    stateless   = false
  }
}

resource "oci_core_subnet" "acx_public_subnet" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.acx_vcn.id
  cidr_block        = "10.0.1.0/24"
  display_name      = "acx-public-subnet"
  dns_label         = "acxpub"
  route_table_id    = oci_core_route_table.acx_rt.id
  security_list_ids = [oci_core_security_list.acx_security_list.id]
}

# Private subnet for the GPU burst host: no public IP, egress via NAT.
resource "oci_core_subnet" "acx_private_subnet" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.acx_vcn.id
  cidr_block                 = "10.0.2.0/24"
  display_name               = "acx-private-subnet"
  dns_label                  = "acxpriv"
  route_table_id             = oci_core_route_table.acx_private_rt.id
  security_list_ids          = [oci_core_security_list.acx_gpu_security_list.id]
  prohibit_public_ip_on_vnic = true
}

# --- Compute ---

resource "oci_core_instance" "acx_backend" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = "acx-backend"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 4
    memory_in_gbs = 24
  }

  source_details {
    source_type             = "image"
    source_id               = var.ubuntu_image_ocid
    boot_volume_size_in_gbs = 200
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.acx_public_subnet.id
    assign_public_ip = true
    display_name     = "acx-backend-vnic"
    hostname_label   = "acx-backend"
  }

  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }

  freeform_tags = {
    "project" = "acx"
    "env"     = "production"
  }
}

resource "oci_core_instance" "acx_gpu_burst" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = "acx-gpu-burst"
  shape               = var.gpu_shape

  # First-boot must complete cloud-init (enable acx-gpu-vlm.service) before any
  # STOP. OCI "state=STOPPED" at create still boots to RUNNING then STOPs, which
  # races runcmd (VLMFIX-S2-05). Safer path: create RUNNING so cloud-init finishes;
  # operator stops after first boot (see infra/oci/README.md). Idle reaper then
  # keeps cost controlled.
  state = "RUNNING"

  source_details {
    source_type             = "image"
    source_id               = var.gpu_image_ocid
    boot_volume_size_in_gbs = var.gpu_boot_volume_size_in_gbs
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.acx_private_subnet.id
    assign_public_ip = false
    display_name     = "acx-gpu-burst-vnic"
    hostname_label   = "acx-gpu-burst"
  }

  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
    user_data           = base64encode(file("${path.module}/gpu-cloud-init.yaml"))
  }

  freeform_tags = {
    "project"       = "acx"
    "env"           = "production"
    "role"          = "gpu-burst"
    "scale_to_zero" = "true"
    "purpose"       = "gpu-spike-bench"
  }
}
