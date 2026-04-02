// This file is generated from packages/shared-contracts/schemas/workbench-media-item.schema.json.

export interface WorkbenchMediaItem {
  id: number;
  title: string;
  status: 'missing' | 'complete';
  thumbnailUrl: string | null;
  altText: string | null;
  editUrl: string | null;
  tags: string[];
}
