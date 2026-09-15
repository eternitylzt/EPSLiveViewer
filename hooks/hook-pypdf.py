"""Keep unencrypted PDF editing independent of optional crypto toolkits."""

excludedimports = ["cryptography", "Crypto", "pypdf._crypt_providers._cryptography",
                   "pypdf._crypt_providers._pycryptodome"]
