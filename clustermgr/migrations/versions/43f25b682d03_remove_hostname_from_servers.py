"""remove hostname from servers

Revision ID: 43f25b682d03
Revises: 4e32059aca93
Create Date: 2017-09-07 19:12:26.194829

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '43f25b682d03'
down_revision = '4e32059aca93'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("ldap_server") as batch_op:
        batch_op.drop_constraint(u'unique_hostname', type_='unique')
        batch_op.drop_column('hostname')

    with op.batch_alter_table("oxauth_server") as batch_op:
        batch_op.drop_column('hostname')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('oxauth_server', sa.Column('hostname', sa.VARCHAR(length=255), nullable=True))
    op.add_column('ldap_server', sa.Column('hostname', sa.VARCHAR(length=150), nullable=True))
    op.create_unique_constraint(u'unique_hostname', 'ldap_server', ['hostname'])
    # ### end Alembic commands ###
