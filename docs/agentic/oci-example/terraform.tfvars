# Copy this file to terraform.tfvars and populate with actual values
# DO NOT commit terraform.tfvars to version control (add to .gitignore)

# OCI Authentication (copy from ~/.oci/config)
tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaarnwywmplftprwcpsytd2g5wjxht45o4jgpidrjhulnzv24qp7q5q"
user_ocid        = "ocid1.user.oc1..aaaaaaaaqv4hxbuqwelghdxkmfnvx5w2pyysv3prgstgje5czfxh4sphrwaq"
fingerprint      = "ac:72:f7:2f:d9:e9:a3:7b:9c:70:f1:46:b8:09:1c:d0"
private_key_path = "~/.oci/oci_api_key.pem"
region           = "us-ashburn-1" # Home region (Always Free requirement)

# Compartment (use tenancy OCID for root compartment)
compartment_ocid = "ocid1.tenancy.oc1..aaaaaaaarnwywmplftprwcpsytd2g5wjxht45o4jgpidrjhulnzv24qp7q5q"

# SSH Access
ssh_public_key_path = "~/.ssh/id_ed25519.pub"

# SSH CIDR Allowlist (restrict to your IP for security)
# Get your IP: curl -s ifconfig.me
ssh_allowed_cidrs = [
  "0.0.0.0/0" # WARNING: Allow SSH from anywhere - restrict in production!
]

# Example: Restrict to specific IP
# ssh_allowed_cidrs = ["203.0.113.42/32"]

