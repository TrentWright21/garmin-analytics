import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

// Entry point. Provides the full multi-page view (launched from the app list)
// and an optional glance card (the swipe-up list on glance-capable devices).
class WaypointApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
    }

    function onStop(state as Dictionary?) as Void {
    }

    // The full app: a paged view driven by a behavior delegate.
    function getInitialView() {
        var view = new WaypointView();
        return [view, new WaypointDelegate(view)];
    }

    // The glance card. The (:glance) annotation lets the SDK drop this entirely
    // on devices that don't support glances, so the app still builds there.
    (:glance)
    function getGlanceView() {
        return [new WaypointGlanceView()];
    }

    // Fired when the user edits apiUrl / apiToken in the app settings.
    function onSettingsChanged() as Void {
        WatchUi.requestUpdate();
    }
}
