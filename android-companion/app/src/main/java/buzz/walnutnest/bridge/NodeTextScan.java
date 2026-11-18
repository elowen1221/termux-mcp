package buzz.walnutnest.bridge;

import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Read-only, bounded text-node traversal for deeply nested Compose windows.
 * Returns ONLY candidate text nodes and original child-index paths. It never
 * infers message roles or writes messages.
 */
final class NodeTextScan {
    static final int MAX_DEPTH = 128;
    static final int MAX_NODES = 2048;
    static final int MAX_RESULTS = 128;
    static final int MAX_TEXT_CHARS = 16000;
    static final int MAX_TOTAL_CHARS = 131072;

    private NodeTextScan() {}

    private static final class Budget {
        int visited;
        int emitted;
        int totalChars;
        int maxDepthSeen;
        boolean truncated;
    }

    static JSONObject scan(AccessibilityNodeInfo root) throws Exception {
        if (root == null) throw new IllegalStateException("Accessibility root unavailable");
        Budget budget = new Budget();
        JSONArray nodes = new JSONArray();
        walk(root, "root", 0, false, budget, nodes);
        JSONObject result = new JSONObject();
        result.put("nodes", nodes);
        result.put("visited_nodes", budget.visited);
        result.put("max_depth_seen", budget.maxDepthSeen);
        result.put("emitted_nodes", budget.emitted);
        result.put("truncated", budget.truncated);
        return result;
    }

    private static void walk(
            AccessibilityNodeInfo node,
            String path,
            int depth,
            boolean parentEditable,
            Budget budget,
            JSONArray results
    ) throws Exception {
        if (node == null || budget.truncated) return;
        if (depth > MAX_DEPTH || budget.visited >= MAX_NODES) {
            budget.truncated = true;
            return;
        }
        budget.visited++;
        budget.maxDepthSeen = Math.max(budget.maxDepthSeen, depth);

        CharSequence clazz = node.getClassName();
        String className = clazz == null ? "" : clazz.toString();
        boolean editable = parentEditable || node.isEditable()
                || className.contains("EditText");
        if (editable) return; // Do not traverse unsent-draft descendants.

        CharSequence rawText = node.getText();
        if (rawText != null && rawText.length() > 0 && rawText.length() <= MAX_TEXT_CHARS) {
            String text = rawText.toString().trim();
            if (!text.isEmpty() && !"null".equals(text)) {
                if (budget.emitted >= MAX_RESULTS
                        || budget.totalChars + text.length() > MAX_TOTAL_CHARS) {
                    budget.truncated = true;
                    return;
                }
                JSONObject record = new JSONObject();
                record.put("path", path);
                record.put("class", className);
                record.put("text", text);
                record.put("editable", false);
                results.put(record);
                budget.emitted++;
                budget.totalChars += text.length();
            }
        }

        int count = node.getChildCount();
        if (depth >= MAX_DEPTH && count > 0) {
            budget.truncated = true;
            return;
        }
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                walk(child, path + "/" + i, depth + 1, false, budget, results);
            }
            if (budget.truncated) break;
        }
    }
}
