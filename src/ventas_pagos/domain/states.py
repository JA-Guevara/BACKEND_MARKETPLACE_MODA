"""Commerce state transitions, independent of HTTP and persistence."""
TRANSITIONS = {"paid": {"processing"}, "processing": {"shipped"}, "shipped": {"delivered"}}

#: Medios con los que se puede cobrar en el mostrador (RF18).
#:
#: `cash` es el unico que da vuelto; los otros tres se cobran por el importe
#: exacto y dejan un comprobante del terminal o de la billetera.
MEDIOS_CAJA = ("cash", "qr", "card", "transfer")
