import React from 'react';
import { createRoot } from 'react-dom/client';
import { GuidedPrototypePage } from '../../js/admin/pages/guided/GuidedPrototypePage';
import '../../js/admin/styles/main.scss';
createRoot(document.getElementById('alt-context-admin')!).render(<React.StrictMode><GuidedPrototypePage /></React.StrictMode>);
