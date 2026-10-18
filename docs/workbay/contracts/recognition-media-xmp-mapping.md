---
title: Recognition Media XMP Mapping
status: active
boundary_owner: wp-proxy
description: Mapping between `/recognition/media/identities?include_debug=true` payload fields and persisted IPTC/ACX XMP fields.
---

# Recognition Media XMP Mapping

## Scope

This contract defines the v4.13.1 mapping used by the WordPress plugin when persisting face metadata into image XMP packets.

- Target files: original uploaded JPEG/PNG only.
- Packet model: one XMP packet with `Iptc4xmpExt` and `acx` namespaces.
- Age/gender are intentionally excluded.

## Source Payload

Source endpoint (via plugin proxy):

- `GET /wp-json/acx/v1/recognition/media-identities?media_ids[]=<id>&include_debug=true`

Required source fields per identity:

- `cluster_label`
- `bbox.x`
- `bbox.y`
- `bbox.width`
- `bbox.height`
- `debug_metrics.pose.pitch`
- `debug_metrics.pose.yaw`
- `debug_metrics.pose.roll`
- `debug_metrics.det_score`
- `debug_metrics.landmark_quality`

## Mapping Table

| Source | XMP Field | Transform |
| --- | --- | --- |
| `cluster_label` | `Iptc4xmpExt:Name` | Trimmed string; skip identity if empty/null. |
| `bbox.x`, `bbox.width`, image width | `Iptc4xmpExt:rbX` | Center point: `(x + width/2) / image_width`; normalized to `0..1`. |
| `bbox.y`, `bbox.height`, image height | `Iptc4xmpExt:rbY` | Center point: `(y + height/2) / image_height`; normalized to `0..1`. |
| `bbox.width`, image width | `Iptc4xmpExt:rbW` | `width / image_width`; normalized to `0..1`. |
| `bbox.height`, image height | `Iptc4xmpExt:rbH` | `height / image_height`; normalized to `0..1`. |
| constant | `Iptc4xmpExt:rbShape` | `rectangle` |
| constant | `Iptc4xmpExt:rbUnit` | `relative` |
| `debug_metrics.pose.pitch` | `acx:Pitch` | Float |
| `debug_metrics.pose.yaw` | `acx:Yaw` | Float |
| `debug_metrics.pose.roll` | `acx:Roll` | Float |
| `debug_metrics.det_score` | `acx:DetScore` | Float |
| `debug_metrics.landmark_quality` | `acx:LandmarkQuality` | Float |

## Exclusions

These fields are not persisted in v4.13.1:

- `debug_metrics.age`
- `debug_metrics.gender`
- `debug_metrics.match_similarity`
- `debug_metrics.similarity_threshold`

## Coordinate Source of Truth

Image dimensions are sourced from WordPress attachment metadata:

- `wp_get_attachment_metadata($attachment_id)['width']`
- `wp_get_attachment_metadata($attachment_id)['height']`

Backend identity payloads do not provide canonical original image dimensions for this transform.

## Cluster Refresh Compatibility

When cluster mutations trigger XMP refresh (relabel/reassign/merge/split/create/revert), the plugin resolves affected media IDs via `GET /recognition/clusters/{cluster_id}/members`.

Deployments may return either shape:

- Flat array: `[{"media_id": 123, ...}, ...]`
- Envelope: `{"members": [{"media_id": 123, ...}]}`

The plugin intentionally supports both shapes during transition.
