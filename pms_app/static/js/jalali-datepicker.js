/**
 * Init Jalali datepicker on all .jalali-datepicker / [data-jdp] inputs.
 * Requires: @majidh1/jalalidatepicker (loaded from CDN in base.html)
 */
(function () {
  function init() {
    if (typeof jalaliDatepicker === 'undefined') {
      console.warn('jalaliDatepicker library not loaded');
      return;
    }

    jalaliDatepicker.startWatch({
      selector: '.jalali-datepicker, input[data-jdp="true"]',
      time: false,
      autoHide: true,
      hideAfterChange: true,
      showTodayBtn: true,
      showEmptyBtn: true,
      topSpace: 4,
      bottomSpace: 4,
      overflowSpace: -10,
      // Persian digits optional – library handles both
      persianDigits: false,
      minDate: 'attr',
      maxDate: 'attr',
      separatorChars: {
        date: '/'
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Re-init after dynamic form loads (optional hook)
  window.ProjectAgentInitJalaliDatepicker = init;
  window.iProjectInitJalaliDatepicker = init;
})();
