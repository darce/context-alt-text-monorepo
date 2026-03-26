import { useAuditEvents, useExportJobStatus, useRetentionStatus } from '../../hooks/useRetentionStatus';

export const useRetentionPageQueries = (exportJobId: string | null, auditPage: number, auditPageSize: number) => {
  const retentionQuery = useRetentionStatus();
  const exportJobStatusQuery = useExportJobStatus(exportJobId);
  const auditQuery = useAuditEvents({ limit: auditPageSize, offset: auditPage * auditPageSize });

  return {
    retentionQuery,
    exportJobStatusQuery,
    auditQuery,
  };
};
