-- Check cluster representatives for the problematic clusters
-- Cluster a1d31ce9-8150-4199-8be8-5c0f296891ac (Ryann Wiseman)
-- Cluster ba14c5ec-b4ef-4d2a-b54c-89a37cb1a266 (cluster-0edc6b7c)

SET app.bypass_rls = 'true';

-- Check cluster details
SELECT 
    id,
    label,
    identity_count,
    similarity_threshold,
    clustering_algorithm,
    created_at
FROM identity_clusters
WHERE id IN (
    'a1d31ce9-8150-4199-8be8-5c0f296891ac',
    'ba14c5ec-b4ef-4d2a-b54c-89a37cb1a266'
)
ORDER BY created_at;

-- Check if representatives exist for these clusters
SELECT 
    cluster_id,
    COUNT(*) as representative_count,
    ARRAY_AGG(identity_id) as rep_identity_ids
FROM identity_cluster_representatives
WHERE cluster_id IN (
    'a1d31ce9-8150-4199-8be8-5c0f296891ac',
    'ba14c5ec-b4ef-4d2a-b54c-89a37cb1a266'
)
GROUP BY cluster_id;

-- Check all representatives in the database
SELECT COUNT(*) as total_representatives
FROM identity_cluster_representatives;

-- Check cluster membership
SELECT 
    ic.label,
    im.cluster_id,
    mi.media_id,
    mi.id as identity_id
FROM media_identities mi
JOIN identity_members im ON im.identity_id = mi.id
JOIN identity_clusters ic ON ic.id = im.cluster_id
WHERE mi.media_id IN (2868, 2851)
ORDER BY mi.media_id;
