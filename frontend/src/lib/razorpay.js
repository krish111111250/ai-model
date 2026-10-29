const CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js';

let loading = null;

/**
 * Load Razorpay's checkout.js once, on first use.
 *
 * Not a <script> tag in index.html: most visits never upgrade, and every one
 * of them would pay for a third-party script. The promise is shared, so two
 * quick clicks do not inject the script twice, and it is dropped on failure
 * so a later click can retry after a network blip.
 */
export function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve(window.Razorpay);

  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const script = document.createElement('script');

      script.src = CHECKOUT_SRC;
      script.async = true;
      script.onload = () =>
        window.Razorpay
          ? resolve(window.Razorpay)
          : reject(new Error('Razorpay checkout did not initialise.'));
      script.onerror = () => {
        script.remove();
        reject(new Error('Could not load Razorpay checkout. Check your connection.'));
      };

      document.body.appendChild(script);
    }).catch((error) => {
      loading = null;
      throw error;
    });
  }

  return loading;
}
