// Validate the exact MWCC audit program after headless import or reuse.
// @category Analysis

import ghidra.app.script.GhidraScript;

import java.util.Locale;

public class MwccAuditStatus extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1 || !args[0].matches("(?i)[0-9a-f]{64}")) {
            throw new IllegalArgumentException("expected one SHA-256 argument");
        }
        if (currentProgram == null) {
            throw new IllegalStateException("no current program");
        }

        String expectedSha = args[0];
        String actualSha = currentProgram.getExecutableSHA256();
        if (actualSha == null || !expectedSha.equalsIgnoreCase(actualSha)) {
            throw new IllegalStateException(
                "compiler SHA-256 mismatch: expected=" + expectedSha + " actual=" + actualSha);
        }

        int functionCount = currentProgram.getFunctionManager().getFunctionCount();
        if (functionCount <= 0) {
            throw new IllegalStateException("compiler project has no functions");
        }
        println("MWCC_AUDIT_STATUS {\"sha256\":\"" +
            actualSha.toLowerCase(Locale.ROOT) + "\",\"function_count\":" +
            functionCount + "}");
    }
}
