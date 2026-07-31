// This file is generated from packages/shared-contracts/schemas/workbench-media-item.schema.json.

export interface WorkbenchMediaItem {
  id: number;
  title: string;
  status: 'missing' | 'complete';
  thumbnailUrl: string | null;
  altText: string | null;
  /**
   * True when the server holds the durable empty-alt decorative marker
   * (acx_alt_decorative=1). Distinct from altText===null (never described).
   * Emitted by class-api.php list producer; never inferred from alt alone.
   */
  isDecorative: boolean;
  editUrl: string | null;
  tags: string[];
}
