
EXAMPLES = [

    ("Hello — display strings",
     'display "Hello World" semi\n'
     'display "Welcome to Crystal" semi\n'),

    ("Variable declarations",
     "integer age equalto 20 semi\n"
     "decimal pi equalto 3.14 semi\n"
     'word name equalto "Ali" semi\n'
     "logic flag equalto yes semi\n"
     "display age semi\n"
     "display name semi\n"),

    ("Arithmetic expression",
     "integer a equalto 5 semi\n"
     "integer b equalto 3 semi\n"
     "integer c equalto a plus b mul 2 semi\n"
     "display c semi\n"),

    ("Sum function",
     "/// function that returns the sum of two integers\n"
     "fun sum (( x : integer , y : integer ))\n"
     "{{\n"
     "    integer total equalto x plus y semi\n"
     "    back total semi\n"
     "}}\n"
     "\n"
     "integer a equalto 10 semi\n"
     "integer b equalto 20 semi\n"
     'display "sum function ready" semi\n'),

    ("For loop (floop)",
     "/// print numbers 1 to 5\n"
     "integer i semi\n"
     "floop (( i equalto 1 semi i is_less 6 semi i equalto i plus 1 ))\n"
     "{{\n"
     "    display i semi\n"
     "}}\n"),

    ("While loop (wloop)",
     "/// countdown from 5 to 1\n"
     "integer n equalto 5 semi\n"
     "wloop (( n is_grtr 0 ))\n"
     "{{\n"
     "    display n semi\n"
     "    n equalto n minus 1 semi\n"
     "}}\n"),

    ("Do-while loop (dloop)",
     "/// runs the body at least once\n"
     "integer i equalto 1 semi\n"
     "dloop\n"
     "{{\n"
     '    display "iteration" semi\n'
     "    i equalto i plus 1 semi\n"
     "}}\n"
     "wloop (( i is_less 4 )) semi\n"),

    ("If / Elif / Else (check / elif / uncheck)",
     "/// selection — grade from marks\n"
     "integer marks equalto 75 semi\n"
     "check (( marks grtr= 90 ))\n"
     "{{\n"
     '    display "Grade A" semi\n'
     "}}\n"
     "elif (( marks grtr= 70 ))\n"
     "{{\n"
     '    display "Grade B" semi\n'
     "}}\n"
     "uncheck\n"
     "{{\n"
     '    display "Grade C" semi\n'
     "}}\n"),

    ("Input + condition (insrt + check)",
     "/// read age, then decide\n"
     "integer age semi\n"
     "insrt age semi\n"
     "check (( age grtr= 18 ))\n"
     "{{\n"
     '    display "Adult" semi\n'
     "}}\n"
     "uncheck\n"
     "{{\n"
     '    display "Minor" semi\n'
     "}}\n"),

    ("Full demo (function + loop + condition)",
     "fun square (( x : integer ))\n"
     "{{\n"
     "    integer r equalto x mul x semi\n"
     "    back r semi\n"
     "}}\n"
     "\n"
     "integer n equalto 3 semi\n"
     "integer i semi\n"
     "floop (( i equalto 1 semi i is_less= n semi i equalto i plus 1 ))\n"
     "{{\n"
     "    check (( i is_it 2 ))\n"
     "    {{\n"
     '        display "two" semi\n'
     "    }}\n"
     "    uncheck\n"
     "    {{\n"
     "        display i semi\n"
     "    }}\n"
     "}}\n"),
]
