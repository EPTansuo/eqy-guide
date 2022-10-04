#!/usr/bin/env python3
#
# Equivalence Checking with Yosys (eqy)
#
# Copyright (C) 2020 Claire Wolf <claire@symbioticeda.com>
# Copyright (C) 2020 N. Engelhardt <nak@symbioticeda.com>
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#
import argparse, types, re
import os, sys, tempfile, shutil
import shlex
##yosys-sys-path##

from eqy_job import EqyJob, EqyTask

def exit_with_error(error, retcode=1):
    print("ERROR:", error, file=sys.stderr)
    exit(retcode)

def root_path():
    fn = getattr(sys.modules['__main__'], '__file__')
    root_path = os.path.abspath(os.path.dirname(fn))
    return root_path

class DictAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        assert isinstance(getattr(namespace, self.dest), dict), "Use ArgumentParser.set_defaults() to initialize {} to dict()".format(self.dest)
        name = option_string.lstrip(parser.prefix_chars).replace("-", "_")
        getattr(namespace, self.dest)[name] = values

def parse_args():
    parser = argparse.ArgumentParser(prog="eqy",
            usage="%(prog)s [options] <config>.eqy")
    parser.set_defaults(exe_paths=dict())

    parser.add_argument("eqyfile", metavar="<config>.eqy", type=argparse.FileType('r'),
            help=".eqy configuration file (use - for stdin)")

    dirargs = parser.add_mutually_exclusive_group()
    dirargs.add_argument("-c", "--continue", action="store_true", dest="cont",
            help="re-run using existing workdir")
    dirargs.add_argument("-f", "--force", action="store_true", dest="force",
            help="remove workdir if it already exists")
    dirargs.add_argument("-b", "--backup", action="store_true", dest="backup",
            help="backup workdir if it already exists")
    dirargs.add_argument("-t", "--tmp", action="store_true", dest="tmpdir",
            help="run in a temporary workdir (remove when finished)")

    parser.add_argument("-d", metavar="<dirname>", dest="workdir",
            help="set workdir name. default: <jobname>")

    parser.add_argument("-m", "--makefiles-only", action="store_true", dest="makefile_only",
            help="generate strategy makefiles and exit")
    parser.add_argument("--init-config-file", metavar=("<filename>", "<gold>", "<gate>"), nargs=3,
            help="create a default .eqy config in <filename> for source files <gold> and <gate>")
    parser.add_argument("--setup", action="store_true", dest="setupmode",
            help="set up the working directory and exit")

    parser.add_argument("-g", "--debug", action="store_true", dest="debugmode",
            help="enable debug mode")

    exes = parser.add_argument_group("path arguments")
    exes.add_argument("--yosys", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths")
    exes.add_argument("--abc", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths")
    exes.add_argument("--smtbmc", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths")
    exes.add_argument("--suprove", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths")
    exes.add_argument("--aigbmc", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths")
    exes.add_argument("--avy", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths")
    exes.add_argument("--btormc", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths")
    exes.add_argument("--pono", metavar="<path_to_executable>",
            action=DictAction, dest="exe_paths",
            help="configure which executable to use for the respective tool")

    args = parser.parse_args()

    exe_paths = {
        "yosys": os.getenv("YOSYS", "yosys"),
        "abc": os.getenv("ABC", "yosys-abc"),
        "smtbmc": os.getenv("SMTBMC", "yosys-smtbmc"),
        "suprove": os.getenv("SUPROVE", "suprove"),
        "aigbmc": os.getenv("AIGBMC", "aigbmc"),
        "avy": os.getenv("AVY", "avy"),
        "btormc": os.getenv("BTORMC", "btormc"),
        "pono": os.getenv("PONO", "pono"),
    }
    for k, v in args.exe_paths.items():
        exe_paths[k] = v

    args.exe_paths = exe_paths

    if args.init_config_file is not None:
        assert args.eqyfile is None
        assert len(args.init_config_file) == 3
        eqy_file = args.init_config_file[0]
        gold_file = args.init_config_file[1]

        gate_file = args.init_config_file[2]
        with open(eqy_file, 'w') as config:
            config.write("""[options]

[gold]
read -formal {0}
prep

[gate]
read -formal {1}
prep

[recode]

[match]

[partition]

[strategy *]
""".format(gold_file, gate_file))
        print("eqy config written to {}".format(eqy_file), file=sys.stderr)
        sys.exit(0)

    return args

def read_config(configfile):
    if configfile is None:
        exit_with_error("No config file given")

    cfg = types.SimpleNamespace()
    cfg_sections = ["options", "gold", "gate", "recode", "match", "partition"]
    named_sections = ["strategy"]
    # TODO: properly initialize options according to meaning
    # how about adding sections only as headers are encountered, so that we can check for existence?
    for s in cfg_sections:
        setattr(cfg, s, list())
    for s in named_sections:
        setattr(cfg, s, dict())

    section = None
    sectionarg = None
    match_default = True
    linenr = 0
    for line in configfile:
        linenr += 1

        # take this out if we want to do --pycode--
        line = line.strip()

        # can we PLEASE have a comment character
        if line == "" or line.startswith('#'):
            continue

        match = re.match(r"^\[(.*)\]\s*$", line)
        if match:
            entries = match.group(1).split()
            if len(entries) == 1 and entries[0] in cfg_sections:
                section, sectionarg = entries[0], None
                continue
            if len(entries) == 2 and entries[0] in named_sections:
                section, sectionarg = entries
                if sectionarg not in getattr(cfg, section):
                    getattr(cfg, section)[sectionarg] = list()
                continue

        if section == "strategy":
            cfg.strategy[sectionarg].append(line)
            continue

        if section == "match" and line == "nodefault":
            match_default = False
            continue

        if section in cfg_sections:
            getattr(cfg, section).append(line)
            continue

        exit_with_error("syntax error in {} line {}".format(configfile.name, linenr))

    if match_default:
        cfg.match.append("gold-match * *")

    return cfg



def setup_workdir(args):
    name = ""
    if not args.workdir:
        if args.eqyfile.name != "<stdin>":
            name = os.path.splitext(os.path.basename(args.eqyfile.name))[0]
            name = re.sub(r'\W+', '', name)

    if args.tmpdir:
        if args.workdir:
            exit_with_error("Cannot use -d with -t")
        args.workdir = tempfile.mkdtemp()
    elif not args.workdir and name == "":
            print("Cannot derive workdir name from config file name. Using temporary directory.")
            args.workdir = tempfile.mkdtemp()
    else:
        if not args.workdir:
            args.workdir = name
        if os.path.exists(args.workdir):
            if args.backup:
                backup_idx = 0
                while os.path.exists("{}.bak{:03d}".format(args.workdir, backup_idx)):
                    backup_idx += 1
                shutil.move(args.workdir, "{}.bak{:03d}".format(args.workdir, backup_idx))
            if args.force:
                shutil.rmtree(args.workdir, ignore_errors=True)
        if args.cont:
            if not os.path.exists(args.workdir):
                exit_with_error("Cannot continue in '{}': no such directory".format(args.workdir))
            if not os.path.isdir(args.workdir):
                exit_with_error("Cannot continue in '{}': not a directory".format(args.workdir))
        else:
            if os.path.exists(args.workdir):
                exit_with_error("Directory '{}' already exists".format(args.workdir))
            os.makedirs(args.workdir)

        for f in "PASS FAIL UNKNOWN ERROR TIMEOUT status".split():
            if os.path.exists(args.workdir + "/" + f):
                os.remove(args.workdir + "/" + f)

def build_gate_gold(args, cfg, job):
    with open(args.workdir + "/gold.ys", "w") as f:
        for line in cfg.gold:
            print(line, file=f)
        print("write_ilang {}/gold.il".format(args.workdir), file=f)
    with open(args.workdir + "/gate.ys", "w") as f:
        for line in cfg.gate:
            print(line, file=f)
        print("write_ilang {}/gate.il".format(args.workdir), file=f)

    gold_task = EqyTask(job, "read_gold", [], "{yosys} -ql {workdir}/gold.log {workdir}/gold.ys".format(yosys=args.exe_paths["yosys"], workdir=args.workdir))
    gold_task.checkretcode = True
    gate_task = EqyTask(job, "read_gate", [], "{yosys} -ql {workdir}/gate.log {workdir}/gate.ys".format(yosys=args.exe_paths["yosys"], workdir=args.workdir))
    gate_task.checkretcode = True

    job.run()
    if (job.status == "ERROR"):
        exit_with_error("Reading sources failed.")

def build_combined(args, cfg, job):
    plugin_path = root_path() + '/../share/yosys/plugins' # for install
    if (not os.path.exists(plugin_path)):
        plugin_path = root_path() # for development
    with open(args.workdir + "/combine.ys", "w") as f:
        print("plugin -i {}/eqy_combine.so".format(plugin_path), file=f)
        print("read_ilang {}/gold.il".format(args.workdir), file=f)
        print("uniquify", file=f)
        print("hierarchy", file=f)
        print("design -stash gold", file=f)
        print("read_ilang {}/gate.il".format(args.workdir), file=f)
        print("uniquify", file=f)
        print("hierarchy", file=f)
        print("design -stash gate", file=f)
        print("{dbg}eqy_combine -gold_ids {wd}/gold.ids -gate_ids {wd}/gate.ids".format(dbg="debug " if args.debugmode else "", wd=args.workdir), file=f)
        print("write_ilang {}/combined.il".format(args.workdir), file=f)

    combine_task = EqyTask(job, "combine", [], "{yosys} -ql {workdir}/combine.log {workdir}/combine.ys".format(yosys=args.exe_paths["yosys"], workdir=args.workdir))
    def check_retcode(retcode):
        if (retcode != 0):
            exit_with_error(f"Failed to combine designs. For details see '{args.workdir}/combine.log'.")
    combine_task.exit_callback = check_retcode

    job.run()

def read_ids(filename):
    ids = dict()
    with open(filename) as f:
        for lineno, line in enumerate(f):
            line = shlex.split(line)
            if len(line) == 0 or line[0].startswith("#"):
                continue
            if len(line) < 3:
                exit_with_error("Syntax error in line {}".format(lineno))
            modname = line[0]
            objname = line[1]
            opts = line[2:]
            if modname not in ids:
                ids[modname] = dict()
            ids[modname][objname] = dict()
            for opt in opts:
                optkey, optval = opt.split("=", maxsplit=1)
                if optkey == "N":
                    if optkey not in ids[modname][objname]:
                        ids[modname][objname][optkey] = list()
                    ids[modname][objname][optkey].append(optval)
                else:
                    ids[modname][objname][optkey] = optval
            if 'w' not in ids[modname][objname] and 'c' not in ids[modname][objname]:
                exit_with_error("Missing type in line {}".format(lineno))
    return ids

def match_module_re(ids, module_re):
    matches = []
    if module_re == "*":
        module_re = ".*"
    p = re.compile(module_re)
    for key in ids:
        match = p.fullmatch(key)
        if match is not None:
            matches.append(key)
    return matches

def match_entity_re(ids, other_ids, entity_re, other_entity_expr):
    matches = []
    if entity_re == "*":
        entity_re = ".*"
    p = re.compile(entity_re)
    for key in ids:
        match = p.fullmatch(key)
        if match is not None:
            val = key
            if other_entity_expr is not None:
                val = match.expand(other_entity_expr)
            if other_ids and val not in other_ids:
                if entity_re == ".*":
                    continue
                exit_with_error(f"Cannot find entity {val}")
            matches.append((key, val))
    return matches

def match_ids(args, cfg):
    gold_ids = read_ids(args.workdir + "/gold.ids")
    gate_ids = read_ids(args.workdir + "/gate.ids")
    used_gold_ids = set()
    used_gate_ids = set()
    with open(args.workdir + "/matched.ids", 'w') as f:
        for line in cfg.match:
            line = line.split()
            if len(line) == 0:
                continue
            if line[0] == "gold-match" and len(line) in [3, 4]:
                for module_match in match_module_re(gold_ids, line[1]):
                    if module_match in gate_ids: #TODO: is this the right way to deal with missing module hierarchy?
                        for entity_match in match_entity_re(gold_ids[module_match], gate_ids[module_match], line[2], line[3] if len(line) == 4 else None):
                            if (module_match, entity_match[0]) in used_gold_ids:
                                continue
                            if (module_match, entity_match[1]) in used_gate_ids:
                                continue
                            print(module_match, entity_match[0], entity_match[1], file=f)
                            used_gold_ids.add((module_match, entity_match[0]))
                            used_gate_ids.add((module_match, entity_match[1]))
            elif line[0] == "gate-match" and len(line) in [3, 4]:
                for module_match in match_module_re(gate_ids, line[1]):
                    if module_match in gold_ids:
                        for entity_match in match_entity_re(gate_ids[module_match], gold_ids[module_match], line[2], line[3] if len(line) == 4 else None):
                            if (module_match, entity_match[0]) in used_gate_ids:
                                continue
                            if (module_match, entity_match[1]) in used_gold_ids:
                                continue
                            print(module_match, entity_match[1], entity_match[0], file=f)
                            used_gate_ids.add((module_match, entity_match[0]))
                            used_gold_ids.add((module_match, entity_match[1]))
            elif line[0] == "gold-nomatch" and len(line) == 3:
                for module_match in match_module_re(gold_ids, line[1]):
                    for entity_match in match_entity_re(gold_ids[module_match], None, line[2], None):
                        used_gold_ids.add((module_match, entity_match[0]))
            elif line[0] == "gate-nomatch" and len(line) == 3:
                for module_match in match_module_re(gate_ids, line[1]):
                    for entity_match in match_entity_re(gate_ids[module_match], None, line[2], None):
                        used_gate_ids.add((module_match, entity_match[0]))
            else:
                exit_with_error(f"Syntax error in match command \"{' '.join(line)}\"")

def partition_ids(args, cfg):
    gold_ids = read_ids(args.workdir + "/gold.ids")


    with open(args.workdir + "/partition_names.ids", "w") as name_f, open(args.workdir + "/partition_nosplit.ids", "w") as nosplit_f, open(args.workdir + "/partition_inputcone.ids", "w") as inputcone_f, open(args.workdir + "/partition_outputcone.ids", "w") as outputcone_f:
        for line in cfg.partition:
            line = line.split()
            if len(line) == 0:
                continue
            elif line[0] == "name" and len(line) == 4:
                for module_match in match_module_re(gold_ids, line[1]):
                    for entity_match, _ in match_entity_re(gold_ids[module_match], line[2], None):
                        print(line[0], module_match, entity_match, line[3], file=name_f)
            elif line[0] == "nosplit" and len(line) == 3:
                for module_match in match_module_re(gold_ids, line[1]):
                    for entity_match, _ in match_entity_re(gold_ids[module_match], line[2], None):
                        print(line[0], module_match, entity_match, file=nosplit_f)
            elif line[0] in ["input-cone", "output-cone"] and len(line) in [3, 4]:
                for module_match in match_module_re(gold_ids, line[1]):
                    for entity_match, _ in match_entity_re(gold_ids[module_match], line[2], None):
                        print(line[0], module_match, entity_match, line[3], file=inputcone_f if line[0]=="input-cone" else outputcone_f)
            else:
                exit_with_error(f"Syntax error in partition command \"{' '.join(line)}\"")

def make_partitions(args, cfg, job):
    partition_ids(args, cfg)
    plugin_path = root_path() + '/../share/yosys/plugins' # for install
    if (not os.path.exists(plugin_path)):
        plugin_path = root_path() # for development
    with open(args.workdir + "/partition.ys", "w") as f:
        print("plugin -i {}/eqy_partition.so".format(plugin_path), file=f)
        print("read_ilang combined.il".format(args.workdir), file=f)
        print("{dbg}eqy_partition -matched_ids matched.ids -partition_names partition_names.ids -nosplit_ids partition_nosplit.ids -create_partition_list partition.list".format(dbg="debug " if args.debugmode else ""), file=f)
    if not os.path.isdir(args.workdir + "/partitions"):
        os.mkdir(args.workdir + "/partitions")

    partition_task = EqyTask(job, "partition", [], "cd {workdir}; {yosys} -ql partition.log partition.ys".format(yosys=args.exe_paths["yosys"], workdir=args.workdir))
    def check_retcode(retcode):
        if (retcode != 0):
            exit_with_error(f"Failed to partition design. For details see '{args.workdir}/partition.log'.")
    partition_task.exit_callback = check_retcode

    job.run()

def write_strategy_dummy(args, cfg, partition, strategy):
    with open(f"{args.workdir}/strategies/{partition}/{strategy}/run.sh", "w") as run_f:
        print("echo PASS > status", file=run_f)
        print(f"echo \"Assumed equivalence of partition '{partition}' using strategy '{strategy}'\"", file=run_f)

def write_strategy_simple(args, cfg, partition, strategy):
    with open(f"{args.workdir}/strategies/{partition}/{strategy}/run.sh", "w") as run_f:
        print( f"""yosys -ql run.log run.ys
if grep "SAT proof finished - no model found: SUCCESS!" run.log > /dev/null ; then
\techo PASS > status
\techo "Proved equivalence of partition '{partition}' using strategy '{strategy}'"
elif grep "SAT proof finished - model found: FAIL!" run.log > /dev/null ; then
\techo UNKNOWN > status
\techo "Could not prove equivalence of partition '{partition}' using strategy '{strategy}'"
else
\techo ERROR > status
\techo "Execution of strategy '{strategy}' on partition '{partition}' encountered an error.\nDetails can be found in '{args.workdir}/strategies/{partition}/{strategy}/run.log'."
\texit 1
fi
exit 0""" , file=run_f)
    with open(f"{args.workdir}/strategies/{partition}/{strategy}/run.ys", "w") as ys_f:
        print(f"read_ilang ../../../partitions/{partition}.il", file=ys_f)
        # TODO: where to put scripts for different strategies
        print(f"miter -equiv -make_assert -ignore_gold_x -flatten gold.{partition} gate.{partition} miter", file=ys_f)
        print("sat -set-init-undef -seq 5 -prove-asserts miter", file=ys_f)

strategies = {
    "dummy": write_strategy_dummy,
    "simple": write_strategy_simple,
    # add strategies here
}

def make_scripts(args, cfg, job):
    partitions = []
    with open(args.workdir + "/partition.list") as f:
        for line in f:
            partitions.append(line.strip())
    if not os.path.isdir(args.workdir + "/strategies"):
        os.mkdir(args.workdir + "/strategies")
    with open(f"{args.workdir}/strategies.mk", "w") as make_f:
        print(".DEFAULT_GOAL := all\n", file=make_f)
        targets = []
        for partition in partitions:
            if not os.path.isdir(f"{args.workdir}/strategies/{partition}"):
                os.mkdir(f"{args.workdir}/strategies/{partition}")
            prev_strategy = None
            for strategy in cfg.strategy:
                if not os.path.isdir(f"{args.workdir}/strategies/{partition}/{strategy}"):
                    os.mkdir(f"{args.workdir}/strategies/{partition}/{strategy}")
                # TODO: ensure unchanged strategies don't get re-run but changed strategies do
                try:
                    strategies[strategy](args, cfg, partition, strategy)
                except KeyError:
                    exit_with_error(f"Unknown strategy '{strategy}'.")
                if prev_strategy:
                    print( f"""strategies/{partition}/{strategy}/status: {prev_strategy}
\t@if grep PASS $^ >/dev/null ; then \\
\t\techo "PASS (cached)" > $@; \\
\telse \\
\t\tbash -c \"cd strategies/{partition}/{strategy}; source run.sh\"; \\
\tfi\n""" , file=make_f)
                else:
                    print(f"strategies/{partition}/{strategy}/status:", file=make_f)
                    print(f"\t@bash -c \"cd strategies/{partition}/{strategy}; source run.sh\"\n", file=make_f)
                prev_strategy = f"strategies/{partition}/{strategy}/status"
            targets.append(prev_strategy)
        print(f".PHONY: all", file=make_f)
        print(f"all: {' '.join(targets)}", file=make_f)
        print( f"""\t@rc=0 ; \\
\tfor f in {' '.join(targets)} ; do \\
\t\tif ! grep -q "PASS" $$f ; then \\
\t\t\tp=$${{f#strategies/}} ; \\
\t\t\tp=$${{p%/*/status}} ; \\
\t\t\techo "Failed to prove equivalence of partition $$p" ; \\
\t\t\trc=1 ; \\
\t\tfi ; \\
\tdone ; \\
\tif [ "$$rc" -eq 0 ] ; then \\
\t\techo "Successfully proved designs equivalent" ; \\
\tfi""", file=make_f)

def run_scripts(args, cfg, job):
    run_task = EqyTask(job, "run", [], f"cd {args.workdir}; make -f strategies.mk")
    def check_output(line):
        match = re.search(r"Failed to prove equivalence", line)
        if match:
            job.update_status("FAIL")
        else:
            match = re.search(r"Successfully proved designs equivalent", line)
            if match:
                job.update_status("PASS")
        return line
    run_task.output_callback = check_output
    def check_retcode(retcode):
        if (retcode != 0):
            exit_with_error(f"A problem occurred during equivalence check.")
    run_task.exit_callback = check_retcode
    job.run()

def validate_config(args, cfg):
    mandatory_cfg_sections = ["gold", "gate"]
    for s in mandatory_cfg_sections:
        if len(getattr(cfg, s)) == 0:
            exit_with_error("section [{}] missing".format(s))
    for strategy in cfg.strategy:
        if strategy not in strategies:
            exit_with_error(f"Unknown strategy '{strategy}'.")

def main():
    args = parse_args()
    cfg = read_config(args.eqyfile)
    validate_config(args, cfg)
    setup_workdir(args)
    if (args.setupmode):
        exit(0)
    print("args =", args)
    print("cfg =", cfg)
    job = EqyJob(args, cfg, [])
    build_gate_gold(args, cfg, job)
    build_combined(args, cfg, job)
    match_ids(args, cfg)
    make_partitions(args, cfg, job)
    make_scripts(args, cfg, job)
    run_scripts(args, cfg, job)
    job.final()

if __name__ == '__main__':
    main()
