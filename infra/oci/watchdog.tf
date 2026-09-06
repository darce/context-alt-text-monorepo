# The dynamic group is restricted to the exact GPU instance OCID and
# compartment, rather than all instances in the compartment. OCI matching-rule
# syntax: https://docs.oracle.com/en-us/iaas/Content/Identity/dynamicgroups/Writing_Matching_Rules_to_Define_Dynamic_Groups.htm
resource "oci_identity_dynamic_group" "acx_gpu_self_stop" {
  compartment_id = var.tenancy_ocid
  description    = "Dynamic group for the ACX GPU instance self-stop watchdog"
  name           = "acx-gpu-self-stop"
  matching_rule  = "All {instance.compartment.id = '${var.compartment_ocid}', instance.id = '${oci_core_instance.acx_gpu_burst.id}'}"
}

# Policy syntax and request.permission conditions:
# https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/corepolicyreference.htm
# InstanceAction requires INSTANCE_POWER_ACTIONS, and OCI condition string
# values must be quoted:
# https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/conditions.htm
resource "oci_identity_policy" "acx_gpu_self_stop" {
  compartment_id = var.tenancy_ocid
  description    = "Permit the ACX GPU instance to stop itself only"
  name           = "acx-gpu-self-stop"

  statements = [
    # The permission condition limits `use instances` to the power-action
    # operation required by `oci compute instance action --action STOP`; the
    # target condition prevents the dynamic-group principal from stopping the
    # backend or any other instance in the compartment.
    "Allow dynamic-group ${oci_identity_dynamic_group.acx_gpu_self_stop.name} to use instances in compartment id ${var.compartment_ocid} where all { request.permission = 'INSTANCE_POWER_ACTIONS', target.instance.id = '${oci_core_instance.acx_gpu_burst.id}' }",
    # The self-stop script performs a separate read after the action returns so
    # an accepted request cannot be mistaken for a terminal STOPPED state.
    "Allow dynamic-group ${oci_identity_dynamic_group.acx_gpu_self_stop.name} to read instances in compartment id ${var.compartment_ocid} where all { request.permission = 'INSTANCE_READ', target.instance.id = '${oci_core_instance.acx_gpu_burst.id}' }",
  ]
}
