package buzz.walnutnest.bridge;

import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Bounded, read-only Accessibility tree serialization.
 *
 * Compose may nest many non-semantic layout nodes before exposing any text.
 * Bound the traversal by depth AND total nodes to avoid dumping a huge tree.
 */
final class NodeTree {
    static final int MAX_DEPTH = 40;
    static final int MAX_NODES = 1024;
    static final int MAX_TEXT_CHARS = 16000;

    private NodeTree() {}

    private static final class Budget {
        int visited = 0;
        boolean truncated = false;
    }

    static JSONObject compact(AccessibilityNodeInfo root, int depth, int maxDepth) throws Exception {
        Budget budget = new Budget();
        JSONObject result = compactBounded(root, depth, Math.max(1, Math.min(MAX_DEPTH, maxDepth)), budget);
        if (result == null) throw new IllegalStateException("No Accessibility root available");
        // Consumers must reject a partial traversal before selecting a capture node.
        result.put("truncated", budget.truncated);
        result.put("visited_nodes", budget.visited);
        return result;
    }

    private static JSONObject compactBounded(
            AccessibilityNodeInfo node, int depth, int maxDepth, Budget budget) throws Exception {
        if (node == null) return null;
        if (budget.visited >= MAX_NODES) {
            budget.truncated = true;
            return null;
        }
        budget.visited += 1;

        JSONObject entry = new JSONObject();
        entry.put("class", String.valueOf(node.getClassName()));
        CharSequence rawText = node.getText();
        entry.put("text", rawText == null || rawText.length() > MAX_TEXT_CHARS
                ? JSONObject.NULL : rawText.toString());
        CharSequence description = node.getContentDescription();
        entry.put("desc", description == null || description.length() > MAX_TEXT_CHARS
                ? JSONObject.NULL : description.toString());
        entry.put("id", node.getViewIdResourceName());
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        entry.put("bounds", new JSONArray(new int[]{bounds.left, bounds.top, bounds.right, bounds.bottom}));
        entry.put("clickable", node.isClickable());
        entry.put("editable", node.isEditable());

        if (depth < maxDepth) {
            JSONArray children = new JSONArray();
            for (int index = 0; index < node.getChildCount(); index++) {
                AccessibilityNodeInfo child = node.getChild(index);
                if (child == null) continue;
                JSONObject serialized = compactBounded(child, depth + 1, maxDepth, budget);
                if (serialized == null) {
                    if (budget.truncated) break;
                    continue;
                }
                children.put(serialized);
            }
            entry.put("children", children);
        } else if (node.getChildCount() > 0) {
            // Even if we did not hit the total node budget, a depth cutoff
            // would hide deeper Compose text. Do not claim a complete tree.
            budget.truncated = true;
        }
        return entry;
    }
}
