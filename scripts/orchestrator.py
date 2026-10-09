import os
import csv
import json

def load_blueprints():
    matrix_path = os.path.join('references', 'naics_matrix.json')
    with open(matrix_path, 'r') as f:
        return json.load(f)

def construct_local_pitch(row, matrix):
    name = row.get('Legal Business Name', 'Business Owner')
    poc = row.get('POC Name', 'Team')
    naics = row.get('NAICS Code', 'default').strip()
    city = row.get('City', 'your area')
    
    # Match data against NAICS matrix blueprints
    info = matrix.get(naics, matrix['default'])
    
    # Establish routing channel parameters
    if naics in ['236220', '561720', '333415']:
        channel = "Phone/SMS"
        pitch = f"Hi {poc}, noticed {name} is bidding on federal jobs out of {city}. We set up a local, offline app that lets estimators drop a 300-page municipal RFP in and pull material specs out in 10 minutes instead of days. Worth a quick look for your crew?"
    else:
        channel = "Email"
        pitch = f"Hi {poc},\n\nNoticed {name} handles federal contracts under NAICS {naics}. Government jobs require strict data security, meaning tools like public ChatGPT leak internal records.\n\nWe set up local, air-gapped language models that automate operational documentation behind your private firewall—zero data leaves your servers.\n\nI have a brief data sheet showing how this layout handles isolation compliance. Can I drop the file here?\n\nBest,\n[Your Name]"

    return channel, info['bottleneck'], info['solution'], pitch

def main():
    if not os.path.exists('leads.csv'):
        print("[!] Input 'leads.csv' missing. Create it before initializing workflow.")
        return

    print("[*] Launching Local GovIntel Pipeline inside Claude Code environment...")
    matrix = load_blueprints()
    processed_count = 0

    with open('leads.csv', mode='r', encoding='utf-8') as infile, \
         open('output_pitches.csv', mode='w', encoding='utf-8', newline='') as outfile:
        
        reader = csv.DictReader(infile)
        fieldnames = [
            'Legal Business Name', 'Website', 'NAICS Code', 'POC Name', 
            'POC Email', 'POC Phone', 'Target Channel', 'Detected Bottleneck', 
            'Proposed Local Solution', 'Tailored Outreach Script'
        ]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            channel, bottleneck, solution, pitch = construct_local_pitch(row, matrix)
            
            writer.writerow({
                'Legal Business Name': row.get('Legal Business Name'),
                'Website': row.get('Website'),
                'NAICS Code': row.get('NAICS Code'),
                'POC Name': row.get('POC Name'),
                'POC Email': row.get('POC Email'),
                'POC Phone': row.get('POC Phone'),
                'Target Channel': channel,
                'Detected Bottleneck': bottleneck,
                'Proposed Local Solution': solution,
                'Tailored Outreach Script': pitch
            })
            processed_count += 1

    print(f"[✓] Execution Finished. Compiled {processed_count} ready-to-use entries inside output_pitches.csv.")

if __name__ == "__main__":
    main()
