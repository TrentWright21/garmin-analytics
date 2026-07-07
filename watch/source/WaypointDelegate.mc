import Toybox.WatchUi;
import Toybox.Lang;

// Input handling for the full app view. Works on both button and touch devices:
//   - button watches: next/previous page + Start (select) to refresh
//   - touch watches: swipe left/up = next, right/down = previous
class WaypointDelegate extends WatchUi.BehaviorDelegate {
    hidden var mView;

    function initialize(view) {
        BehaviorDelegate.initialize();
        mView = view;
    }

    function onNextPage() {
        mView.nextPage();
        return true;
    }

    function onPreviousPage() {
        mView.prevPage();
        return true;
    }

    function onSelect() {
        mView.refresh();
        return true;
    }

    function onSwipe(evt) {
        var dir = evt.getDirection();
        if (dir == WatchUi.SWIPE_UP || dir == WatchUi.SWIPE_LEFT) {
            mView.nextPage();
        } else if (dir == WatchUi.SWIPE_DOWN || dir == WatchUi.SWIPE_RIGHT) {
            mView.prevPage();
        }
        return true;
    }
}
