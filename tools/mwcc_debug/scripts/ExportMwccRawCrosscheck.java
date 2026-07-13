// Export numeric cross-check facts for the exact retail MWCC compiler.
// @category Analysis

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressRange;
import ghidra.program.model.address.AddressRangeIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Comparator;
import java.util.Iterator;
import java.util.Locale;
import java.util.TreeSet;

public class ExportMwccRawCrosscheck extends GhidraScript {
    private static final String SCHEMA = "mwcc-ghidra-raw-crosscheck.v1";

    private static final class Row {
        final long address;
        final String kind;
        final String json;

        Row(long address, String kind, String json) {
            this.address = address;
            this.kind = kind;
            this.json = json;
        }
    }

    private static String escape(String value) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < value.length(); i++) {
            char character = value.charAt(i);
            switch (character) {
                case '\\': out.append("\\\\"); break;
                case '"': out.append("\\\""); break;
                case '\b': out.append("\\b"); break;
                case '\f': out.append("\\f"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (character < 0x20) {
                        out.append(String.format("\\u%04x", (int) character));
                    } else {
                        out.append(character);
                    }
            }
        }
        return out.toString();
    }

    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            out.append(String.format("%02x", value & 0xff));
        }
        return out.toString();
    }

    private static long numeric(Address address) {
        return address.getOffset() & 0xffffffffL;
    }

    private static void add(
            TreeSet<Row> rows, long address, String kind, String json) {
        rows.add(new Row(address, kind, json));
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2 || !args[0].matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException(
                "expected lowercase compiler SHA-256 and output path");
        }
        if (currentProgram == null) {
            throw new IllegalStateException("no current program");
        }
        String expectedSha = args[0];
        String actualSha = currentProgram.getExecutableSHA256();
        if (actualSha == null || !expectedSha.equals(actualSha.toLowerCase(Locale.ROOT))) {
            throw new IllegalStateException(
                "compiler SHA-256 mismatch: expected=" + expectedSha + " actual=" + actualSha);
        }

        TreeSet<Row> rows = new TreeSet<>(
            Comparator.comparingLong((Row row) -> row.address)
                .thenComparing(row -> row.kind)
                .thenComparing(row -> row.json));
        add(rows, -1, "metadata",
            "{\"record_kind\":\"metadata\",\"schema_version\":\"" + SCHEMA +
            "\",\"compiler_sha256\":\"" + expectedSha + "\"}");

        Iterator<Function> functions =
            currentProgram.getFunctionManager().getFunctions(true);
        while (functions.hasNext()) {
            monitor.checkCancelled();
            Function function = functions.next();
            long entry = numeric(function.getEntryPoint());
            add(rows, entry, "function",
                "{\"record_kind\":\"function\",\"address\":" + entry +
                ",\"name\":\"" + escape(function.getName()) + "\"}");
            AddressRangeIterator ranges = function.getBody().getAddressRanges(true);
            while (ranges.hasNext()) {
                AddressRange range = ranges.next();
                long start = numeric(range.getMinAddress());
                long end = numeric(range.getMaxAddress());
                add(rows, start, "function-body-range",
                    "{\"record_kind\":\"function-body-range\",\"address\":" + start +
                    ",\"function_entry\":" + entry + ",\"end\":" + end + "}");
            }

            // Preserve the retained bounded audit's exact traversal as an
            // independent regression occurrence stream.  This deliberately
            // counts overlapping function ownership more than once and stops
            // when getNext() first leaves the body, so it does not visit a
            // later disjoint body range.  The global instruction/call rows
            // below remain the canonical unique cross-check facts.
            Instruction retainedInstruction =
                getInstructionAt(function.getEntryPoint());
            while (retainedInstruction != null &&
                    function.getBody().contains(retainedInstruction.getAddress())) {
                if (retainedInstruction.getFlowType().isCall()) {
                    long callAddress = numeric(retainedInstruction.getAddress());
                    boolean computed = retainedInstruction.getFlowType().isComputed();
                    for (Address targetAddress : retainedInstruction.getFlows()) {
                        long target = numeric(targetAddress);
                        add(rows, callAddress, "retained-body-call",
                            "{\"record_kind\":\"retained-body-call\",\"address\":" +
                            callAddress + ",\"function_entry\":" + entry +
                            ",\"target\":" + target + ",\"computed\":" +
                            computed + "}");
                    }
                }
                retainedInstruction = retainedInstruction.getNext();
            }
        }

        Iterator<Instruction> instructions =
            currentProgram.getListing().getInstructions(true);
        while (instructions.hasNext()) {
            monitor.checkCancelled();
            Instruction instruction = instructions.next();
            long address = numeric(instruction.getAddress());
            byte[] bytes = instruction.getBytes();
            add(rows, address, "instruction",
                "{\"record_kind\":\"instruction\",\"address\":" + address +
                ",\"size\":" + bytes.length + ",\"bytes_hex\":\"" + hex(bytes) + "\"}");

            Address[] flows = instruction.getFlows();
            boolean computed = instruction.getFlowType().isComputed();
            if (instruction.getFlowType().isCall()) {
                for (Address targetAddress : flows) {
                    long target = numeric(targetAddress);
                    add(rows, address, "call",
                        "{\"record_kind\":\"call\",\"address\":" + address +
                        ",\"target\":" + target + ",\"computed\":" + computed + "}");
                }
            }
            if (computed) {
                if (flows.length == 0) {
                    add(rows, address, "computed-transfer",
                        "{\"record_kind\":\"computed-transfer\",\"address\":" + address +
                        ",\"target\":0}");
                } else {
                    for (Address targetAddress : flows) {
                        long target = numeric(targetAddress);
                        add(rows, address, "computed-transfer",
                            "{\"record_kind\":\"computed-transfer\",\"address\":" + address +
                            ",\"target\":" + target + "}");
                    }
                }
            }
            for (Reference reference : instruction.getReferencesFrom()) {
                if (reference.getReferenceType().isFlow()) {
                    continue;
                }
                long target = numeric(reference.getToAddress());
                add(rows, address, "data-reference",
                    "{\"record_kind\":\"data-reference\",\"address\":" + address +
                    ",\"target\":" + target + "}");
            }
        }

        functions = currentProgram.getFunctionManager().getFunctions(true);
        while (functions.hasNext()) {
            monitor.checkCancelled();
            Function function = functions.next();
            long target = numeric(function.getEntryPoint());
            for (Reference reference : getReferencesTo(function.getEntryPoint())) {
                if (reference.getReferenceType().isFlow()) {
                    continue;
                }
                long address = numeric(reference.getFromAddress());
                add(rows, address, "function-pointer-reference",
                    "{\"record_kind\":\"function-pointer-reference\",\"address\":" + address +
                    ",\"target\":" + target + "}");
            }
        }

        Path output = Path.of(args[1]);
        try (BufferedWriter writer = Files.newBufferedWriter(
                output,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE)) {
            for (Row row : rows) {
                writer.write(row.json);
                writer.newLine();
            }
        }
    }
}
