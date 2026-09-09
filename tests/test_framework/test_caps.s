# test_caps.s — exercise CHERI memory ops
# Assumes startup.json initialized c1, c2, c10

# Store a byte through c1
addi   x5, x0, 0x42
sb.cap x5, c1

# Load it back
lb.cap x6, c1

# Inspect c1
cgetperm x7, c1
cgetbase x8, c1

# Capability store (c2 into c1's address)
sc.cap   c2, c1
lc.cap   c3, c1

# Done
ebreak
