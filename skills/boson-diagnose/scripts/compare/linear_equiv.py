"""Prove affine combinational equivalence at common register cut points.

This compares pin functions, not register clock/reset/latch semantics. Those
semantics and the correspondence of register instances must already be known.
Exit 0: equal, 1: unequal, 2: unsupported or inconclusive. Stdlib only.
"""
import argparse
import re
import sys

from _cmp import Graph, read_liberty, read_netlist, truth_table, verilog_statements


class LinearChecker:
    def __init__(self, library):
        self.library = library
        self.basis = {}
        self.forms = {}

    def variable(self, key):
        # Bit zero is the constant; every other bit is a common boundary input.
        if key not in self.basis:
            self.basis[key] = 1 << (len(self.basis) + 1)
        return self.basis[key]

    def form(self, reference, output):
        key = reference, output
        if key not in self.forms:
            cell = self.library[reference]
            if cell.three_state:
                raise ValueError("three-state cell " + reference)
            inputs = sorted(cell.inputs)
            table, count = truth_table(cell.functions[output], inputs)
            bias = table & 1
            coefficients = [i for i in range(count) if (table >> (1 << i) & 1) ^ bias]
            for row in range(1 << count):
                linear = sum(row >> i & 1 for i in coefficients) % 2
                if (table >> row & 1) != linear ^ bias:
                    raise ValueError("nonlinear cell " + reference)
            self.forms[key] = [inputs[i] for i in coefficients], bias
        return self.forms[key]

    def evaluate(self, graph):
        if graph.unknown_types:
            raise ValueError("unknown library cells")
        driven = set()
        for outputs in graph.outputs:
            for _, net in outputs:
                if net in driven or net in (0, 1):
                    raise ValueError("multiple drivers or driven constant")
                driven.add(net)
        ports = {
            net: self.variable(("input", name))
            for name, (direction, net) in graph.nl.top_ports.items()
            if direction == "input"
        }
        if driven.intersection(ports):
            raise ValueError("cell drives a primary input")
        memo = {0: 0, 1: 1}
        visiting = set()

        def net_value(net):
            if net in memo:
                return memo[net]
            if net in visiting:
                raise ValueError("combinational cycle")
            visiting.add(net)
            if net in ports:
                value = ports[net]
            elif net not in graph.driver:
                raise ValueError("undriven net " + graph.nl.net_name[net])
            else:
                instance, pin = graph.driver[net]
                reference = graph.nl.inst_type[instance]
                if self.library[reference].kind == "sequential":
                    value = self.variable(("state", graph.nl.inst_name[instance], pin))
                else:
                    terms, value = self.form(reference, pin)
                    pins = dict(graph.nl.pins[instance])
                    for term in terms:
                        value ^= net_value(pins[term])
            visiting.remove(net)
            memo[net] = value
            return value

        checks = {
            ("output", name): net_value(net)
            for name, (direction, net) in graph.nl.top_ports.items()
            if direction == "output"
        }
        for instance, reference in enumerate(graph.nl.inst_type):
            if self.library[reference].kind == "sequential":
                for pin, net in graph.inputs[instance]:
                    checks[("capture", graph.nl.inst_name[instance], pin)] = net_value(net)
        return checks

    def compare(self, gold, gate):
        interfaces = [
            {name: direction for name, (direction, _) in graph.nl.top_ports.items()}
            for graph in (gold, gate)
        ]
        if not interfaces[0] or interfaces[0] != interfaces[1] or "inout" in interfaces[0].values():
            raise ValueError("unmatched or bidirectional top-level ports")
        before, after = self.evaluate(gold), self.evaluate(gate)
        if before.keys() != after.keys():
            raise ValueError("unmatched boundary objects")
        if not before:
            raise ValueError("no observable boundary functions")
        return len(before), [key for key in before if before[key] != after[key]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--liberty", required=True, action="append")
    parser.add_argument("--top", required=True)
    parser.add_argument("gold")
    parser.add_argument("gate")
    args = parser.parse_args(argv)
    try:
        library = read_liberty(args.liberty)
        checker = LinearChecker(library)
        graphs = []
        for path in (args.gold, args.gate):
            for _, statement in verilog_statements(path):
                literals = re.findall(r"\b\d*'[sS]?[bBoOdDhH]([0-9a-fA-F_xXzZ?]+)", statement)
                if any(re.search(r"[xXzZ?]", literal) for literal in literals):
                    raise ValueError("unknown or high-impedance literal")
            graphs.append(Graph(read_netlist(path, args.top), library))
        boundaries, mismatches = checker.compare(*graphs)
        print("exact linear cut-point equivalence:", boundaries, "boundaries,",
              len(checker.basis), "variables,", len(mismatches), "mismatches")
        if mismatches:
            print("first mismatch:", mismatches[0])
        return int(bool(mismatches))
    except (ValueError, KeyError, RecursionError, OSError) as error:
        print("INCONCLUSIVE:", error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
