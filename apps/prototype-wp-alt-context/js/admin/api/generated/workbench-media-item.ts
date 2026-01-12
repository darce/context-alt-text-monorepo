// This file is generated from packages/shared-contracts/schemas/workbench-media-item.schema.json.

export interface WorkbenchMediaItem {
  id: number;
  title: string;
  status: 'missing' | 'complete';
  thumbnailUrl: string | null;
  altText: string | null;
  mimeType: string;
  editUrl: string | null;
  updatedAt: string;
  dimensions: {
    width: number | null;
    height: number | null;
  } | null;
  tags: string[];
}
