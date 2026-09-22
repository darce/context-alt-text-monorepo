export type WordPressTestConnectionGuidanceProps = {
  onClose: () => void;
  onReturnToKeys: () => void;
};

export function WordPressTestConnectionGuidance({ onClose, onReturnToKeys }: WordPressTestConnectionGuidanceProps) {
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="wordpress-guidance-title" className="acx-portal">
      <h2 id="wordpress-guidance-title">WordPress Test Connection guidance</h2>
      <ol>
        <li>Copy the secret once.</li>
        <li>Paste it into the WordPress plugin&apos;s API-key field.</li>
        <li>Run the plugin&apos;s Test Connection control.</li>
        <li>Return here to inspect, rotate, or revoke the key.</li>
      </ol>
      <p>
        Never send the secret in a URL, screenshot, log, or support ticket. Exact plugin menu labels are unverified in
        this portal and are not claimed here.
      </p>
      <div className="acx-portal-actions">
        <button type="button" className="acx-btn acx-btn-primary" onClick={onReturnToKeys}>
          Back to API keys
        </button>
        <button type="button" className="acx-btn" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
