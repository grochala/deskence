// Test-only helper, installed exclusively into the isolated test HOME.
export default class TestHelper {
    enable() {
        global.context.unsafe_mode = true;
    }

    disable() {
        global.context.unsafe_mode = false;
    }
}
