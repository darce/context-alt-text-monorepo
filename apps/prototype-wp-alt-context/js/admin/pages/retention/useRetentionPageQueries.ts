import { useExportJobStatus, useRetentionStatus } from '../../hooks/useRetentionStatus';

export const useRetentionPageQueries = (exportJobId: string | null) => {
  const retentionQuery = useRetentionStatus();
  const exportJobStatusQuery = useExportJobStatus(exportJobId);

  return {
    retentionQuery,
    exportJobStatusQuery,
  };
};
