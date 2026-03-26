import {
  useApplyRetentionPreset,
  useDownloadExportJobData,
  useExportTenantData,
  useImportTenantData,
  usePurgeTenantData,
  useUpdateRetentionPolicy,
} from '../../hooks/useRetentionStatus';

export const useRetentionPageMutations = () => {
  const updatePolicy = useUpdateRetentionPolicy();
  const exportMutation = useExportTenantData();
  const purgeMutation = usePurgeTenantData();
  const importMutation = useImportTenantData();
  const applyPreset = useApplyRetentionPreset();
  const downloadJobData = useDownloadExportJobData();

  return {
    updatePolicy,
    exportMutation,
    purgeMutation,
    importMutation,
    applyPreset,
    downloadJobData,
  };
};
