from .application import db


class LDAPServer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(150))
    port = db.Column(db.Integer)
    role = db.Column(db.String(10))
    starttls = db.Column(db.Boolean)
    server_id = db.Column(db.Integer)
    replication_id = db.Column(db.Integer)
    manager_dn = db.Column(db.String(200))
    manager_pw = db.Column(db.String(200))

    def __init__(self, hostname, port, role, starttls, s_id,
                 r_id, manager_dn, manager_pw):
        self.hostname = hostname
        self.port = port
        self.role = role
        self.starttls = starttls
        self.server_id = s_id
        self.replication_id = r_id
        self.manager_dn = manager_dn
        self.manager_pw = manager_pw

    def __repr__(self):
        return '<Server %s:%d>' % (self.hostname, self.port)
