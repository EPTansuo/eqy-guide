
Reference for .eqy file format
==============================

A ``.eqy`` file consists of sections. Each section start with a single-line
section header in square brackets.

Options section
---------------

The optional ``[options]`` section contains one config setting per line, in the
form of key-value pairs.

.. code-block:: text

   [options]
   awesome yes
   foobar 15

Gold and gate sections
----------------------

The mandatory ``[gold]`` and ``gate`` sections contains the Yosys script that
reads and elaborates the "gold" and "gate" versions of the design under test.
For example, for a simple project contained in a single design file
``mytest.sv``, and a synthesis output file ``synth.v``, with the
top-module ``mytest``:

.. code-block:: text

   [gold]
   read -sv mytest.sv
   prep -top mytest

   [gate]
   read -sv synth.v
   prep -top mytest

Run ``yosys`` in a terminal window and enter ``help`` on the Yosys prompt
for a command list. Run ``help <command>`` for a detailed description of the
command, for example ``help prep``.

Recode sections
---------------

Recode sections contain encodings for FSM state registers, for the cases when
the sythesis tool changes those encodings. (Alternatively the state registers
can be excluded as match points and strategies for sequential equivalence
checking can be employed for proving equivalence of the FSM as a whole.)

These sections start with a header that contains two arguments: A module
name from the (gold) design and the name of a wire within that module. (Those
arguments are actually both regular expressions, but are rarely used to match
more than one entity.)

The section itself listst binary representation of values in the gold design
and their corresponding gate encodings. Values not listed should never be
produced by the gold design.

.. code-block:: text

   [recode mytest state]
   00 001
   01 010
   10 100

Match sections
--------------

Match sections contain rules for matching net names in the gold design to net
names in the gate design. The match section header contains an optional pattern
matching module names. The lines within the match section are only applied to
modules matching that pattern, or all modules if the pattern is omitted.

.. code-block:: text

   [match axi_xbar_*]
   gate-match *_ff \0

TBD: gold-match, gate-match, gold-nomatch, gate-nomatch

Partition sections
------------------

Partition sections contain rules for creating matching partitions in the gold
and gate designs.  The partition section header contains an optional pattern
matching module names. The lines within the partition section are only applied
to modules matching that pattern, or all modules if the pattern is omitted.

.. code-block:: text

   [match axi_xbar_*]
   name /^(reader|buffer|arbiter|writer)_([0-7])$/ pipeline_\1

[no]autogroup
.............

Marking a net as noautogroup will prevent the auto grouping mechanism to
group this net with other nets into the same primitive partition. Per default
autogrouping does group nets when

- they are driven by the same cell, either in the gold or gate design, or
- gold nets are aliases, i.e. are implemented by the same gate net.

group and nogroup
.................

The ``group <pattern>`` command is used to group everything matching the given
pattern into the same primitive partition.

The ``group <pattern> <pattern>`` command is pairing matches for the first pattern with the sets
of nets matching the (dependent) second pattern, and is grouping them accordingly.

The ``nogroup <pattern>`` command prevents all further ``group`` commands from
matching the specified nets.

stop and nostop
...............

Marking a net as ``nostop`` prevents that net from becoming a primary input of
a primitive partition. (This has no effect on nets that are module inputs.)

The ``stop <pattern>`` command prevents all further ``nostop`` commands from
matching the speciefied nets. (The default behavior is "stop" for all nets.)

name and noname
...............

The ``name <pattern> <string>`` command is looking for nets matching the given pattern,
and then applies the given name to the partition that contains that net as primary
output.

If multiple ``name`` commands assign the same name to different entities, then the
corresponding partitions will be merged into one partition with the given name. If
multiple ``name`` commands apply to the same partition, then the earlier name command
will be used to name the partition. (Both names are used for merging partitions tho.)

The ``noname <pattern>`` command can be used to prevent further name commands from
mathing the given nets.

merge and nomerge
.................

The ``merge`` and ``nomerge`` commands work similar to ``group`` and ``nogroup``,
but creates non-primitive partitions by merging the primitive partitions generated
by the grouping commands.

path statements
...............

The ``path <pattern> <pattern>`` command will determine the shortest path from the
first net to the second net, and then merge all partitions along that path.

If the first pattern matches a net name then the partition generating that net is
not included in the path itself. If the first pattern matches a partition name then
that partition is included in the path.

If the second pattern matches a net name then partitions consuming that signal
are not included in the path itself. If the second pattern matches a partition name
then that partition is included in the path.

sticky and nosticky
...................

The ``sticky <pattern>`` command marks nets as sticky. The partition generating the
sticky net as primary output will then be merged with any partition using the
sticky net as primary input.

The ``nosticky <pattern>`` command preents further ``sticky`` commands from matching
the given net.

split and nosplit
.................

The ``nosplit`` command operates on a multi-bit wire and merges the partitions
that generate the individial wire bits as primary outputs.

The ``split`` command prevents further ``nosplit`` commands from matching
the given net.

final statements
................

The ``final <pattern>`` command marks the partitions generating the
nets matching the pattern as final. No furter statements will have any
effect on a partition after it is marked as final.

Strategy sections
-----------------

Each strategy section creates a verification strategy used to prove
partitions to be equal. The section header contains the name of the
strategy as an argument.

.. code-block:: text

   [strategy simple]
   apply axi_xbar_*
   use satseq
   depth 10

use statements
..............

The ``use strategy_type`` command selects a strategy type for this strategy. Each
strategy type defines its own custom commands for the strategy section. For example,
the ``depth`` command in the example above is a custom command only understood by
the ``satseq`` strategy type.

apply and noapply
.................

The ``apply <pattern> [<pattern>]`` command is used to enable the given strategy
in modules matching the first pattern, for partitions matching
the second pattern. The ``noapply <pattern> [<pattern>]`` command prevents
further ``apply`` commands in the same strategy section from matching the
specified partitions. If the second pattern is omitted, then the strategy will
be applied to all partitions in the modules matching the first pattern.

Pattern Syntax
--------------

Patterns are comma-seperated lists of any combinations of the following
types of expressions.

- names of modules or nets, or shell wildcard pattern matching those names,
- regular expressions matching enity names, enclosed in forward slashes,
- at-sign (@) followed by an attribute name, matching all entities with that attribute set,
- at-sign and attribute name, followed by an equal sign (=) and an attribute value,
- or ampercent-sign (&) followed by a partition name.

A regular expression can be enclosed in ``//i`` instead of ``//``, in which
case it is evaluated case-insensitive.

Attribute names and partition names can also be shell wildcard patterns, or
regular expressions.

The partition name syntax is only available in ``path``, ``final``, and ``apply``
statements.

In commands that accept pairs of patterns, numeric backreferences (\0, \1, \2) and
named backreferences (\g<1>, \g<name>) are replaced in the second pattern by
the contents of the corresponding group from the first pattern.

If the first pattern in a pair used the at-sign syntax for attributes, then \g<attr>
in the second pattern is replaced with the attribute name and \g<value> with
the corresponding attribute value.
