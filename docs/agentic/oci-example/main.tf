terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
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

resource "oci_core_vcn" "acx_vcn" {
  compartment_id = var.compartment_ocid
  display_name   = "acx-vcn"
  dns_label      = "acxvcn"
  cidr_blocks    = ["10.0.0.0/16"]
}

resource "oci_core_internet_gateway" "acx_igw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-igw"
  enabled        = true
}

resource "oci_core_route_table" "acx_rt" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-rt"

  route_rules {
    description       = "Default route to internet"
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.acx_igw.id
  }
}

resource "oci_core_security_list" "acx_sl" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-sl"

  egress_security_rules {
    description = "Allow all outbound"
    destination = "0.0.0.0/0"
    protocol    = "all"
    stateless   = false
  }

  dynamic "ingress_security_rules" {
    for_each = var.ssh_allowed_cidrs
    content {
      description = "SSH from ${ingress_security_rules.value}"
      source      = ingress_security_rules.value
      protocol    = "6"
      stateless   = false

      tcp_options {
        min = 22
        max = 22
      }
    }
  }

  ingress_security_rules {
    description = "HTTPS"
    source      = "0.0.0.0/0"
    protocol    = "6"
    stateless   = false

    tcp_options {
      min = 443
      max = 443
    }
  }

  dynamic "ingress_security_rules" {
    for_each = var.enable_app_port ? var.app_allowed_cidrs : []
    content {
      description = "Temporary app-port debug from ${ingress_security_rules.value}"
      source      = ingress_security_rules.value
      protocol    = "6"
      stateless   = false

      tcp_options {
        min = var.app_port
        max = var.app_port
      }
    }
  }
}

resource "oci_core_subnet" "acx_public_subnet" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.acx_vcn.id
  display_name               = "acx-public-subnet"
  dns_label                  = "public"
  cidr_block                 = "10.0.1.0/24"
  route_table_id             = oci_core_route_table.acx_rt.id
  security_list_ids          = [oci_core_security_list.acx_sl.id]
  prohibit_public_ip_on_vnic = false
}

resource "oci_core_instance" "acx_backend" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = "acx-backend"
  shape               = var.shape

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_in_gbs
  }

  source_details {
    source_type             = "image"
    source_id               = var.ubuntu_image_ocid
    boot_volume_size_in_gbs = var.boot_volume_size_in_gbs
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

  freeform_tags = var.freeform_tags
}

data "oci_core_vnic_attachments" "acx_backend_vnics" {
  compartment_id = var.compartment_ocid
  instance_id    = oci_core_instance.acx_backend.id
}

data "oci_core_vnic" "acx_backend_primary_vnic" {
  vnic_id = data.oci_core_vnic_attachments.acx_backend_vnics.vnic_attachments[0].vnic_id
}
