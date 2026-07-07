import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Application;
import Toybox.Communications;

// The glance card: two lines (readiness headline + the one-line action).
// Self-contained (its own fetch) so it stays within the glance memory budget
// and is dropped cleanly on devices without glance support.
(:glance)
class WaypointGlanceView extends WatchUi.GlanceView {
    hidden var mData;
    hidden var mStatus;

    function initialize() {
        GlanceView.initialize();
        var cached = Application.Storage.getValue("briefing");
        mData = (cached instanceof Lang.Dictionary) ? cached : null;
        mStatus = (mData != null) ? "" : "Loading...";
    }

    function onShow() {
        var url = Application.Properties.getValue("apiUrl");
        if (url == null || !(url instanceof Lang.String) || url.length() == 0) {
            mStatus = "Set apiUrl";
            WatchUi.requestUpdate();
            return;
        }
        var params = {};
        var token = Application.Properties.getValue("apiToken");
        if (token != null && token instanceof Lang.String && token.length() > 0) {
            params.put("token", token);
        }
        var options = {
            :method => Communications.HTTP_REQUEST_METHOD_GET,
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };
        var base = url as Lang.String;
        Communications.makeWebRequest(base + "/api/watch/briefing", params, options, method(:onResponse));
    }

    function onResponse(
        code as Lang.Number,
        resp as Null or Lang.Dictionary or Lang.String or Toybox.PersistedContent.Iterator
    ) as Void {
        if (code == 200 && resp instanceof Lang.Dictionary) {
            mData = resp;
            mStatus = "";
            Application.Storage.setValue("briefing", resp);
        } else if (mData == null) {
            mStatus = "Offline";
        }
        WatchUi.requestUpdate();
    }

    function onUpdate(dc) {
        var h = dc.getHeight();
        if (mData == null) {
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(0, h / 2, Graphics.FONT_TINY, "Waypoint - " + mStatus,
                Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
            return;
        }
        var band = str(mData.get("readiness_band"));
        var score = mData.get("readiness_score");
        var line1 = "Readiness " + ((score == null) ? "--" : score.toString()) + "  " + band.toUpper();
        dc.setColor(bandColor(band), Graphics.COLOR_TRANSPARENT);
        dc.drawText(0, h * 0.30, Graphics.FONT_TINY, line1,
            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(0, h * 0.70, Graphics.FONT_XTINY, shorten(str(mData.get("action")), 34),
            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}
