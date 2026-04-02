// This file is generated from packages/shared-contracts/schemas/workbench-media-detail.schema.json.

export interface WorkbenchMediaDetail {
  id: number;
  mimeType: string | null;
  updatedAt: string | null;
  dimensions: {
    width: number | null;
    height: number | null;
  } | null;
  xmpPersistence: Record<string, unknown> | null;
}