jQuery(document).ready(function($) {
    $(".transaction-row-click td a").click(function(e) {
        e.stopPropagation();
    });
});

$(document).ready(function() {
  $('.double-scroll').doubleScroll();
});